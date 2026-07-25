"""Shared test fixtures."""

from __future__ import annotations

import pytest

from backend.core.resource_guard import ResourceGuard, ResourceSnapshot
from config.settings import Settings


class FakeSampler:
    """A sampler with settable readings — no hardware required."""

    vram_total_bytes = 16 * 10**9
    ram_total_bytes = 64 * 10**9

    def __init__(self, gpu: bool = True) -> None:
        self.gpu = gpu
        self.ratios: dict[str, float | None] = {
            "vram": 0.30 if gpu else None,
            "gpu_util": 0.20 if gpu else None,
            "ram": 0.30,
            "cpu": 0.10,
            "disk": 0.40,
        }
        if not gpu:
            self.vram_total_bytes = None

    def sample(self) -> ResourceSnapshot:
        return ResourceSnapshot(ratios=dict(self.ratios))


@pytest.fixture
def settings() -> Settings:
    # Deterministic defaults matching the reference spec.
    return Settings(
        resource_ceiling=0.96,
        resource_soft=0.88,
        rolling_window=3,
        hysteresis_margin=0.06,
        ladder_l1=0.88,
        ladder_l2=0.92,
        ladder_l3=0.94,
        ladder_l4=0.96,
    )


@pytest.fixture
def sampler() -> FakeSampler:
    return FakeSampler()


@pytest.fixture
def guard(sampler: FakeSampler, settings: Settings) -> ResourceGuard:
    return ResourceGuard(sampler=sampler, settings=settings)


def feed_steady(guard: ResourceGuard, sampler: FakeSampler, vram: float) -> None:
    """Drive the guard to a steady VRAM reading.

    Clears the rolling window first so the smoothed value equals `vram` with no
    residue from a prior reading — the hysteresis memory lives in the guard's
    degradation *level*, not in the window (the window only suppresses spikes).
    This makes level transitions depend cleanly on (current level, new value).
    """
    guard._window.clear()
    sampler.ratios["vram"] = vram
    for _ in range(guard._window.maxlen or 3):
        guard.feed(sampler.sample())
