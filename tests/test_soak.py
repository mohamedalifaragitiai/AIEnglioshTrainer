"""A short soak proves the guard's invariants hold under concurrent load."""

from __future__ import annotations

from backend.core.soak import run_soak
from config.settings import Settings


async def test_short_soak_is_healthy():
    settings = Settings(sample_interval_s=0.02)
    stats = await run_soak(0.6, hot_workers=4, cold_workers=4, settings=settings)
    # Hot path never blocked; guard degraded under pressure; cold work deferred.
    assert stats.hot_blocked == 0
    assert stats.errors == 0
    assert stats.max_degradation >= 1
    assert stats.cold_deferred > 0
    assert stats.hot_turns > 0
    assert stats.healthy()
