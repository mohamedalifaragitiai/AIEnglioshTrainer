"""ResourceGuard — the 96% ceiling and graceful-degradation ladder.

This is the component that keeps a resource-constrained host from hanging. It
samples GPU VRAM, GPU utilization, RAM, CPU, and disk on a background async loop,
maintains a short rolling window so a single spike doesn't trip degradation, and
exposes :meth:`acquire` so every heavy operation (STT, LLM, TTS, cold-path jobs)
asks permission before running. The guard never runs work itself — it *advises*
and records; the caller must honor the returned :class:`Admission`.

Design notes
------------
* **Never busy-wait.** The sampler sleeps on an interruptible ``asyncio.Event``.
* **Sampler is injectable.** Tests feed synthetic snapshots via :meth:`feed`
  without any real hardware; production uses :class:`PsutilNvmlSampler`.
* **vLLM reservation is a fixed block.** vLLM grabs ``vllm_vram_fraction`` of VRAM
  at startup; the guard treats that as reserved-not-available rather than free
  VRAM it may hand out (see ``check_startup_budget``).

See ``references/resource-governance.md`` for the full spec.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic, perf_counter
from typing import Literal, Protocol

from backend.core import metrics
from backend.core.logging import get_logger
from config.settings import Settings, get_settings

log = get_logger("resource_guard")

Path = Literal["hot", "cold"]


class Resource(StrEnum):
    VRAM = "vram"
    GPU_UTIL = "gpu_util"
    RAM = "ram"
    CPU = "cpu"
    DISK = "disk"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourceSnapshot:
    """A single reading. Ratios are 0..1; ``None`` means the resource is absent
    (e.g. VRAM on a CPU-only host)."""

    ratios: dict[str, float | None]
    ts: float = field(default_factory=monotonic)

    def peak(self) -> float:
        """Highest known usage ratio across resources (0.0 if all unknown)."""
        vals = [r for r in self.ratios.values() if r is not None]
        return max(vals) if vals else 0.0

    def get(self, resource: Resource | str) -> float | None:
        return self.ratios.get(str(getattr(resource, "value", resource)))


@dataclass(frozen=True)
class ResourceEstimate:
    """What an operation expects to consume. Only fill what applies."""

    vram_gb: float = 0.0
    ram_gb: float = 0.0
    cpu_frac: float = 0.0  # additional CPU load, 0..1
    gpu_util_frac: float = 0.0  # additional GPU compute, 0..1
    is_new_session: bool = False  # gates Level-4 rejection on the hot path
    llm_max_tokens: int | None = None  # baseline the guard may trim under pressure
    llm_context: int | None = None
    # How long this (cold) job has already spent deferred. Past the configured
    # budget the guard stops re-deferring it — see ``acquire``.
    waited_s: float = 0.0


AdmissionKind = Literal["full", "degraded", "defer", "reject"]


@dataclass(frozen=True)
class Admission:
    """The guard's answer. The caller MUST honor it."""

    kind: AdmissionKind
    level: int = 0
    params: dict = field(default_factory=dict)
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.kind in ("full", "degraded")

    @classmethod
    def full(cls, level: int = 0) -> Admission:
        return cls("full", level=level)

    @classmethod
    def degraded(cls, params: dict, reason: str, level: int) -> Admission:
        return cls("degraded", level=level, params=params, reason=reason)

    @classmethod
    def defer(cls, reason: str, level: int) -> Admission:
        return cls("defer", level=level, reason=reason)

    @classmethod
    def reject(cls, reason: str, level: int) -> Admission:
        return cls("reject", level=level, reason=reason)


# ---------------------------------------------------------------------------
# Samplers
# ---------------------------------------------------------------------------


class Sampler(Protocol):
    """Anything that can produce a :class:`ResourceSnapshot`."""

    vram_total_bytes: int | None
    ram_total_bytes: int

    def sample(self) -> ResourceSnapshot: ...


class PsutilNvmlSampler:
    """Real sampler: NVML for GPU (optional), psutil for CPU/RAM/disk.

    If NVML is unavailable (CPU-only host), GPU samples report ``None`` and the
    system still runs on CPU fallbacks.
    """

    def __init__(self, disk_path: str = "."):
        import psutil

        self._psutil = psutil
        self._disk_path = disk_path
        self.ram_total_bytes = psutil.virtual_memory().total

        self._nvml = None
        self._handle = None
        self.vram_total_bytes = None
        try:
            import pynvml  # nvidia-ml-py exposes the ``pynvml`` module

            pynvml.nvmlInit()
            self._nvml = pynvml
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self.vram_total_bytes = int(
                pynvml.nvmlDeviceGetMemoryInfo(self._handle).total
            )
            log.info("nvml_initialized", vram_total_gb=round(self.vram_total_bytes / 1e9, 2))
        except Exception as exc:  # noqa: BLE001 — any failure ⇒ treat GPU as absent
            log.warning("nvml_unavailable", error=str(exc))

        # Prime cpu_percent so the first real reading is meaningful.
        psutil.cpu_percent(interval=None)

    def sample(self) -> ResourceSnapshot:
        ps = self._psutil
        ratios: dict[str, float | None] = {}

        if self._nvml is not None and self._handle is not None:
            try:
                mem = self._nvml.nvmlDeviceGetMemoryInfo(self._handle)
                ratios[Resource.VRAM.value] = mem.used / mem.total
                util = self._nvml.nvmlDeviceGetUtilizationRates(self._handle)
                ratios[Resource.GPU_UTIL.value] = util.gpu / 100.0
            except Exception as exc:  # noqa: BLE001
                log.warning("nvml_sample_failed", error=str(exc))
                ratios[Resource.VRAM.value] = None
                ratios[Resource.GPU_UTIL.value] = None
        else:
            ratios[Resource.VRAM.value] = None
            ratios[Resource.GPU_UTIL.value] = None

        ratios[Resource.RAM.value] = ps.virtual_memory().percent / 100.0
        ratios[Resource.CPU.value] = ps.cpu_percent(interval=None) / 100.0
        disk = ps.disk_usage(self._disk_path)
        ratios[Resource.DISK.value] = disk.used / disk.total

        return ResourceSnapshot(ratios=ratios)

    def shutdown(self) -> None:
        if self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


class ResourceGuard:
    def __init__(self, sampler: Sampler, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._sampler = sampler
        self._window: deque[ResourceSnapshot] = deque(maxlen=self._settings.rolling_window)
        self._level = 0
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

        self.ceiling = self._settings.resource_ceiling
        self.soft = self._settings.resource_soft
        self.margin = self._settings.hysteresis_margin
        self.ladder = self._settings.ladder_thresholds  # (l1, l2, l3, l4)

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Launch the background sampler. Idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        # Seed one immediate sample so the guard has state before the first tick.
        self._take_sample()
        self._task = asyncio.create_task(self._run(), name="resource-guard-sampler")
        log.info("resource_guard_started", interval_s=self._settings.sample_interval_s)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:  # pragma: no cover
                pass
            self._task = None
        log.info("resource_guard_stopped")

    async def _run(self) -> None:
        interval = self._settings.sample_interval_s
        while not self._stop.is_set():
            self._take_sample()
            # Interruptible sleep — wakes immediately on stop(); never busy-waits.
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except TimeoutError:
                pass

    def _take_sample(self) -> None:
        t0 = perf_counter()
        try:
            snap = self._sampler.sample()
        except Exception as exc:  # noqa: BLE001 — a sampler failure must not kill the loop
            log.error("sampler_failed", error=str(exc))
            return
        finally:
            metrics.guard_sample_duration_seconds.observe(perf_counter() - t0)
        self.feed(snap)

    # --- state ingestion (also the test entry point) -----------------------

    def feed(self, snap: ResourceSnapshot) -> None:
        """Ingest a snapshot, update metrics, and recompute the degradation level.

        Tests call this directly with synthetic snapshots — no hardware needed.
        """
        self._window.append(snap)

        # Ceiling-hit accounting uses the raw sample (not the smoothed value).
        for res, ratio in snap.ratios.items():
            if ratio is not None and ratio >= self.ceiling:
                metrics.resource_ceiling_hits_total.labels(resource=res).inc()

        smoothed = self._smoothed()
        for res, ratio in smoothed.ratios.items():
            if ratio is not None:
                metrics.resource_usage_ratio.labels(resource=res).set(ratio)

        self._recompute_level(smoothed)

    def _smoothed(self) -> ResourceSnapshot:
        """Mean of each resource over the rolling window (ignoring ``None``)."""
        if not self._window:
            return ResourceSnapshot(ratios={})
        keys: set[str] = set()
        for s in self._window:
            keys.update(s.ratios.keys())
        out: dict[str, float | None] = {}
        for k in keys:
            vals = [s.ratios[k] for s in self._window if s.ratios.get(k) is not None]
            out[k] = (sum(vals) / len(vals)) if vals else None
        return ResourceSnapshot(ratios=out)

    def _recompute_level(self, smoothed: ResourceSnapshot) -> None:
        peak = smoothed.peak()
        lvl = self._level
        # Escalate: cross the next entry threshold.
        while lvl < 4 and peak >= self.ladder[lvl]:
            lvl += 1
        # De-escalate with hysteresis: only drop once a margin below the level's
        # entry threshold, so the ladder doesn't flap on a boundary.
        while lvl > 0 and peak < self.ladder[lvl - 1] - self.margin:
            lvl -= 1

        if lvl != self._level:
            log.info(
                "degradation_transition",
                from_level=self._level,
                to_level=lvl,
                peak_usage=round(peak, 4),
            )
            self._level = lvl
        metrics.degradation_level.set(lvl)

    # --- introspection -----------------------------------------------------

    def snapshot(self) -> ResourceSnapshot:
        """Latest smoothed snapshot."""
        return self._smoothed()

    def headroom(self, resource: Resource | str) -> float:
        """1.0 - usage_ratio for a resource (1.0 if unknown)."""
        r = self._smoothed().get(resource)
        return 1.0 if r is None else max(0.0, 1.0 - r)

    @property
    def degradation_level(self) -> int:
        return self._level

    # --- admission control -------------------------------------------------

    def _project(self, need: ResourceEstimate) -> dict[str, float | None]:
        """Current smoothed ratios plus the op's estimated additional load."""
        cur = self._smoothed().ratios
        proj = dict(cur)

        def add(res: str, delta_ratio: float) -> None:
            base = cur.get(res)
            if base is not None and delta_ratio:
                proj[res] = base + delta_ratio

        if need.vram_gb and self._sampler.vram_total_bytes:
            add(Resource.VRAM.value, need.vram_gb * 1e9 / self._sampler.vram_total_bytes)
        if need.ram_gb and self._sampler.ram_total_bytes:
            add(Resource.RAM.value, need.ram_gb * 1e9 / self._sampler.ram_total_bytes)
        add(Resource.CPU.value, need.cpu_frac)
        add(Resource.GPU_UTIL.value, need.gpu_util_frac)
        return proj

    @staticmethod
    def _crosses(proj: dict[str, float | None], ceiling: float) -> bool:
        return any(r is not None and r >= ceiling for r in proj.values())

    def _degraded_llm_params(self, need: ResourceEstimate, level: int) -> dict:
        """Trim LLM context/max_tokens as pressure rises (Levels 2-4)."""
        factor = {2: 0.5, 3: 0.33, 4: 0.25}.get(level, 1.0)
        params: dict = {}
        if need.llm_max_tokens is not None:
            params["max_tokens"] = max(32, int(need.llm_max_tokens * factor))
        if need.llm_context is not None:
            params["context"] = max(256, int(need.llm_context * factor))
        return params

    async def acquire(self, need: ResourceEstimate, path: Path) -> Admission:
        """Decide whether an operation may run, and under what constraints.

        Hot path may be *degraded* but is never simply blocked — a live speaker is
        waiting. Cold path is always deferrable under pressure.
        """
        level = self._level
        proj = self._project(need)
        would_cross = self._crosses(proj, self.ceiling)

        if path == "cold":
            if level >= 1 or would_cross:
                # Deferral is only ever a *delay*. On a host whose idle peak sits
                # above ladder_l1 the level never de-escalates, so an unbounded
                # defer is a silent drop: the job re-queues forever and the learner
                # never gets scored. Once a job has out-waited the budget, admit it
                # — but never through the hard ceiling, which is what actually
                # protects the box from freezing.
                starved = need.waited_s >= self._settings.coldpath_max_defer_s
                if starved and not would_cross:
                    metrics.jobs_starved_total.inc()
                    log.info(
                        "coldpath_starvation_admit",
                        waited_s=round(need.waited_s, 1),
                        level=level,
                    )
                    return Admission.degraded(
                        {}, f"admitted after {need.waited_s:.0f}s deferred", level
                    )
                metrics.jobs_deferred_total.inc()
                reason = (
                    "would cross ceiling"
                    if would_cross
                    else f"degradation level {level} — cold work paused"
                )
                return Admission.defer(reason, level)
            return Admission.full(level)

        # --- hot path ---
        # Level 4: protect the in-flight turn, reject only NEW sessions.
        if level >= 4 and need.is_new_session:
            metrics.sessions_rejected_total.inc()
            return Admission.reject("at ceiling — new sessions rejected", level)

        # Trim LLM params when the ladder says so, or when this op alone would cross.
        if level >= 2 or would_cross:
            params = self._degraded_llm_params(need, max(level, 2))
            return Admission.degraded(params, f"degraded at level {level}", level)

        return Admission.full(level)

    # --- startup budget check ---------------------------------------------

    def check_startup_budget(self, min_vram_gb: float) -> tuple[bool, str]:
        """Confirm the minimum viable model set fits under the ceiling *before*
        loading anything — so we refuse to start with an actionable message
        rather than OOM-crashing later.

        Accounts for vLLM's static reservation as a fixed pre-committed block.
        """
        total = self._sampler.vram_total_bytes
        if not total:
            return True, "no GPU detected — CPU fallbacks apply, VRAM budget N/A"

        total_gb = total / 1e9
        current = self._smoothed().get(Resource.VRAM) or 0.0
        current_gb = current * total_gb
        vllm_gb = self._settings.vllm_vram_fraction * total_gb
        needed_gb = current_gb + vllm_gb + min_vram_gb
        ceiling_gb = self.ceiling * total_gb

        ok = needed_gb <= ceiling_gb
        msg = (
            f"VRAM budget: baseline {current_gb:.1f}GB + vLLM {vllm_gb:.1f}GB + "
            f"min set {min_vram_gb:.1f}GB = {needed_gb:.1f}GB vs ceiling "
            f"{ceiling_gb:.1f}GB ({self.ceiling:.0%} of {total_gb:.1f}GB) — "
            f"{'FITS' if ok else 'DOES NOT FIT'}"
        )
        return ok, msg
