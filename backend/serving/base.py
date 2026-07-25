"""Managed models and the registry that loads them through the ResourceGuard.

Every heavy model (STT, GOP, TTS, and the vLLM-served LLMs) is a
:class:`ManagedModel`. The :class:`ModelRegistry` is the single place that:

* computes whether the **minimum resident set** fits under the 96% VRAM ceiling
  and **refuses to start** with an actionable message if it won't (rather than
  OOM-crashing later), and
* loads each enabled model, tracking status and emitting metrics.

The app worker never loads LLM weights — vLLM is a separate process reached over
HTTP (see :mod:`backend.serving.llm_client`). Its VRAM is the guard's fixed
pre-committed block, so it is *not* counted in the min-set sum below; the
non-vLLM GPU models (STT + GOP + TTS) are.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from time import perf_counter

from pydantic import BaseModel

from backend.core import metrics
from backend.core.logging import get_logger
from backend.core.resource_guard import ResourceGuard

log = get_logger("serving")


class ModelStatus(StrEnum):
    DISABLED = "disabled"        # not enabled in settings
    NOT_LOADED = "not_loaded"    # enabled but load not attempted (models off)
    LOADING = "loading"
    LOADED = "loaded"
    UNAVAILABLE = "unavailable"  # deps/weights missing — cannot load
    FAILED = "failed"            # load raised


class ModelKind(StrEnum):
    LLM = "llm"          # served by vLLM (separate process, reserved VRAM)
    STT = "stt"
    GOP = "gop"
    TTS = "tts"


class ModelInfo(BaseModel):
    name: str
    kind: ModelKind
    status: ModelStatus
    device: str
    vram_gb: float          # estimated resident VRAM
    counts_toward_min_set: bool
    detail: str = ""


class ManagedModel(ABC):
    """A model whose lifecycle is gated by the ResourceGuard."""

    kind: ModelKind

    def __init__(self, name: str, *, device: str, vram_gb: float, enabled: bool = True):
        self.name = name
        self.device = device
        self.vram_gb = vram_gb
        self.enabled = enabled
        self.status: ModelStatus = ModelStatus.NOT_LOADED if enabled else ModelStatus.DISABLED
        self.detail = ""

    # vLLM-served models don't count toward the non-vLLM min-set sum (their VRAM is
    # the guard's reserved block); resident GPU models do.
    @property
    def counts_toward_min_set(self) -> bool:
        return self.kind is not ModelKind.LLM and self.device.startswith("cuda")

    @abstractmethod
    def available(self) -> bool:
        """True if imports + weights are present so a load can succeed."""

    @abstractmethod
    async def _load(self) -> None:
        """Do the actual (lazy-imported) load. Raise on failure."""

    async def _unload(self) -> None:  # noqa: B027 — intentional concrete no-op default
        """Release resources. Default no-op; override where needed."""
        return

    async def load(self) -> None:
        """Load the model, timing it and updating status + metrics."""
        if not self.enabled:
            self.status = ModelStatus.DISABLED
            return
        if not self.available():
            self.status = ModelStatus.UNAVAILABLE
            self.detail = "dependencies or weights not present"
            self._emit(loaded=False)
            log.warning("model_unavailable", model=self.name, kind=str(self.kind))
            return
        self.status = ModelStatus.LOADING
        t0 = perf_counter()
        try:
            await self._load()
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the caller here
            self.status = ModelStatus.FAILED
            self.detail = str(exc)
            self._emit(loaded=False)
            log.error("model_load_failed", model=self.name, error=str(exc))
            raise
        metrics.model_load_duration_seconds.labels(self.name, str(self.kind)).observe(
            perf_counter() - t0
        )
        self.status = ModelStatus.LOADED
        self._emit(loaded=True)
        log.info("model_loaded", model=self.name, kind=str(self.kind), vram_gb=self.vram_gb)

    async def unload(self) -> None:
        try:
            await self._unload()
        finally:
            if self.status == ModelStatus.LOADED:
                self.status = ModelStatus.NOT_LOADED
            self._emit(loaded=False)

    def _emit(self, *, loaded: bool) -> None:
        metrics.model_loaded.labels(self.name, str(self.kind)).set(1 if loaded else 0)
        metrics.model_vram_estimate_gb.labels(self.name, str(self.kind)).set(self.vram_gb)

    def info(self) -> ModelInfo:
        return ModelInfo(
            name=self.name,
            kind=self.kind,
            status=self.status,
            device=self.device,
            vram_gb=self.vram_gb,
            counts_toward_min_set=self.counts_toward_min_set,
            detail=self.detail,
        )


class StartupBudgetError(RuntimeError):
    """Raised when the minimum resident set won't fit under the VRAM ceiling."""


class ModelRegistry:
    """Owns the managed models and the guard-gated startup sequence."""

    def __init__(self, guard: ResourceGuard):
        self.guard = guard
        self._models: list[ManagedModel] = []

    def register(self, model: ManagedModel) -> None:
        self._models.append(model)

    @property
    def models(self) -> list[ManagedModel]:
        return list(self._models)

    def min_set_vram_gb(self) -> float:
        """Sum of estimated VRAM for enabled non-vLLM resident GPU models."""
        return sum(
            m.vram_gb for m in self._models if m.enabled and m.counts_toward_min_set
        )

    def budget(self) -> dict:
        min_gb = self.min_set_vram_gb()
        fits, message = self.guard.check_startup_budget(min_gb)
        return {"min_set_vram_gb": round(min_gb, 2), "fits": fits, "detail": message}

    async def load_all(self) -> None:
        """Startup: verify the budget, then load every enabled model.

        Refuses to start (raises :class:`StartupBudgetError`) if the minimum set
        won't fit — an actionable failure instead of a later OOM.
        """
        min_gb = self.min_set_vram_gb()
        fits, message = self.guard.check_startup_budget(min_gb)
        log.info(
            "startup_model_budget",
            min_set_vram_gb=round(min_gb, 2),
            fits=fits,
            detail=message,
        )
        if not fits:
            raise StartupBudgetError(
                f"Refusing to start: minimum resident model set does not fit under the "
                f"{self.guard.ceiling:.0%} VRAM ceiling. {message}. "
                f"Reduce COACH_VLLM_VRAM_FRACTION, move TTS to CPU, or drop the cold 14B."
            )
        for model in self._models:
            await model.load()

    async def unload_all(self) -> None:
        for model in self._models:
            await model.unload()

    def infos(self) -> list[ModelInfo]:
        return [m.info() for m in self._models]
