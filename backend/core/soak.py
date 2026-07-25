"""Soak harness — sustained concurrent load under oscillating resource pressure.

Drives the ResourceGuard with a synthetic sawtooth VRAM signal while many hot-path
and cold-path callers hammer ``acquire`` concurrently, then asserts the load-bearing
invariants hold under pressure:

* the **hot path is never blocked** (a live speaker is waiting) — only degraded;
* **cold work is deferred** while the ceiling is approached;
* the guard actually **climbs the ladder** (pressure was real).

Synthetic pressure only — we never really allocate to 96% (that is the freeze this
exists to prevent). Importable (``run_soak``) so it runs both as a script and a test.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from time import monotonic

from backend.core.logging import get_logger
from backend.core.resource_guard import (
    ResourceEstimate,
    ResourceGuard,
    ResourceSnapshot,
)
from config.settings import Settings, get_settings

log = get_logger("soak")


class RampingSampler:
    """A sampler whose VRAM oscillates between calm and near-ceiling (sawtooth/sine)."""

    vram_total_bytes = 16 * 10**9
    ram_total_bytes = 64 * 10**9

    def __init__(self, speed: float = 8.0):
        self._t0 = monotonic()
        self._speed = speed

    def sample(self) -> ResourceSnapshot:
        x = (monotonic() - self._t0) * self._speed
        vram = 0.30 + 0.66 * (0.5 + 0.5 * math.sin(x))  # ~0.30 .. 0.96
        return ResourceSnapshot(
            ratios={"vram": vram, "gpu_util": 0.30, "ram": 0.30, "cpu": 0.20, "disk": 0.40}
        )


@dataclass
class SoakStats:
    duration_s: float = 0.0
    hot_turns: int = 0
    hot_blocked: int = 0        # MUST stay 0 — hot path never blocks
    cold_processed: int = 0
    cold_deferred: int = 0
    max_degradation: int = 0
    errors: int = 0

    def healthy(self) -> bool:
        return (
            self.errors == 0
            and self.hot_blocked == 0
            and self.max_degradation >= 1
            and self.cold_deferred > 0
        )

    def problems(self) -> list[str]:
        out = []
        if self.errors:
            out.append(f"{self.errors} exception(s) raised")
        if self.hot_blocked:
            out.append(f"hot path blocked {self.hot_blocked}x (must never happen)")
        if self.max_degradation < 1:
            out.append("guard never degraded — pressure not exercised")
        if self.cold_deferred == 0:
            out.append("cold work never deferred under pressure")
        return out


async def run_soak(
    duration_s: float = 2.0,
    *,
    hot_workers: int = 4,
    cold_workers: int = 4,
    settings: Settings | None = None,
) -> SoakStats:
    settings = settings or get_settings().model_copy(update={"sample_interval_s": 0.02})
    guard = ResourceGuard(sampler=RampingSampler(), settings=settings)
    await guard.start()

    stats = SoakStats(duration_s=duration_s)
    stop_at = monotonic() + duration_s

    async def hot_loop() -> None:
        while monotonic() < stop_at:
            try:
                adm = await guard.acquire(ResourceEstimate(gpu_util_frac=0.3), "hot")
                if adm.kind in ("defer", "reject"):
                    stats.hot_blocked += 1
                else:
                    stats.hot_turns += 1
            except Exception:  # noqa: BLE001
                stats.errors += 1
            await asyncio.sleep(0.005)

    async def cold_loop() -> None:
        while monotonic() < stop_at:
            try:
                adm = await guard.acquire(ResourceEstimate(gpu_util_frac=0.3), "cold")
                if adm.kind == "defer":
                    stats.cold_deferred += 1
                else:
                    stats.cold_processed += 1
            except Exception:  # noqa: BLE001
                stats.errors += 1
            await asyncio.sleep(0.005)

    async def monitor() -> None:
        while monotonic() < stop_at:
            stats.max_degradation = max(stats.max_degradation, guard.degradation_level)
            await asyncio.sleep(0.01)

    tasks = (
        [hot_loop() for _ in range(hot_workers)]
        + [cold_loop() for _ in range(cold_workers)]
        + [monitor()]
    )
    try:
        await asyncio.gather(*tasks)
    finally:
        await guard.stop()
    return stats
