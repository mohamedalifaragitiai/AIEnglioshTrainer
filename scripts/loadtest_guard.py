"""Synthetic load test for the ResourceGuard.

Proves the 96% ceiling holds — that the guard climbs the degradation ladder,
defers cold-path work, and rejects new sessions — *before* any real model is
loaded (Phase 0 gate). It ramps **synthetic** VRAM/RAM readings through the guard
rather than really allocating memory: actually driving the box to 96% is exactly
the freeze this project exists to prevent, so we simulate the pressure and assert
the guard reacts correctly.

Run:  uv run python scripts/loadtest_guard.py
Exits non-zero if the guard misbehaves, so it can gate CI.
"""

from __future__ import annotations

import asyncio

from backend.core.logging import configure_logging
from backend.core.resource_guard import (
    Admission,
    ResourceEstimate,
    ResourceGuard,
    ResourceSnapshot,
)
from config.settings import get_settings


class FakeSampler:
    """Sampler whose readings we set by hand to simulate rising pressure."""

    vram_total_bytes = 16 * 10**9
    ram_total_bytes = 64 * 10**9

    def __init__(self) -> None:
        self._vram = 0.30

    def set_vram(self, ratio: float) -> None:
        self._vram = ratio

    def sample(self) -> ResourceSnapshot:
        return ResourceSnapshot(
            ratios={"vram": self._vram, "gpu_util": 0.20, "ram": 0.30, "cpu": 0.10, "disk": 0.40}
        )


def _fill_window(guard: ResourceGuard, sampler: FakeSampler, ratio: float) -> None:
    """Drive the guard to a steady reading (window cleared so there is no residue
    from the previous ramp step; hysteresis lives in the degradation level)."""
    guard._window.clear()
    sampler.set_vram(ratio)
    for _ in range(get_settings().rolling_window):
        guard.feed(sampler.sample())


async def main() -> int:
    configure_logging(level="INFO", json_logs=False)
    settings = get_settings()
    sampler = FakeSampler()
    guard = ResourceGuard(sampler=sampler, settings=settings)

    hot_llm = ResourceEstimate(vram_gb=0.5, llm_max_tokens=512, llm_context=4096)
    hot_new = ResourceEstimate(vram_gb=0.5, is_new_session=True, llm_max_tokens=512)
    cold_job = ResourceEstimate(vram_gb=1.5)

    # (vram ratio, expected degradation level, expected cold admission kind)
    ramp = [
        (0.30, 0, "full"),
        (0.85, 0, "full"),
        (0.89, 1, "defer"),   # ≥88% → Level 1: cold work paused
        (0.93, 2, "defer"),   # ≥92% → Level 2: LLM params trimmed
        (0.945, 3, "defer"),  # ≥94% → Level 3
        (0.965, 4, "defer"),  # ≥96% → Level 4: reject new sessions
        # Hysteresis: coming back down, the level is sticky.
        (0.905, 4, "defer"),  # above L4 exit(0.90) → HOLDS at 4 despite <96%
        (0.80, 0, "full"),    # below every exit margin → full recovery to normal
    ]

    failures = 0
    cols = f"{'VRAM%':>6} {'level':>5} {'exp':>3}  {'cold':>8} {'hot(exist)':>11} {'hot(new)':>10}"
    print("\n" + cols)
    print("-" * 64)
    for ratio, exp_level, exp_cold in ramp:
        _fill_window(guard, sampler, ratio)
        lvl = guard.degradation_level
        cold: Admission = await guard.acquire(cold_job, "cold")
        hot: Admission = await guard.acquire(hot_llm, "hot")
        hot_new_adm: Admission = await guard.acquire(hot_new, "hot")

        ok_level = lvl == exp_level
        ok_cold = cold.kind == exp_cold
        # Hot path must NEVER block an in-flight turn.
        ok_hot_blocks = hot.kind in ("full", "degraded")
        # A new session must be rejected once at the ceiling (Level 4), else allowed.
        ok_new = (hot_new_adm.kind == "reject") if lvl >= 4 else (hot_new_adm.kind != "reject")

        if not (ok_level and ok_cold and ok_hot_blocks and ok_new):
            failures += 1
            mark = "  <-- FAIL"
        else:
            mark = ""
        print(
            f"{ratio*100:6.1f} {lvl:5d} {exp_level:3d}  {cold.kind:>8} "
            f"{hot.kind:>14} {hot_new_adm.kind:>10}{mark}"
        )

    print("-" * 64)
    if failures:
        print(f"FAILED: {failures} mismatch(es) — the ceiling is NOT protecting the box.")
        return 1
    print("PASSED: guard climbs the ladder, defers cold work, and rejects new "
          "sessions at the ceiling — while never blocking the live turn.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
