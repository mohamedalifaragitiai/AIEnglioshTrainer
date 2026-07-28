"""Tests for the ResourceGuard — the load-bearing 96% ceiling.

Covers the degradation ladder, hysteresis (no flapping), spike suppression via the
rolling window, hot-vs-cold admission semantics, VRAM projection, and startup
budgeting. These must pass before any real model is trusted to the box.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.core.resource_guard import (
    PsutilNvmlSampler,
    ResourceEstimate,
    ResourceGuard,
)
from tests.conftest import FakeSampler, feed_steady

# --- ladder transitions ----------------------------------------------------


@pytest.mark.parametrize(
    "vram,expected_level",
    [
        (0.50, 0),
        (0.87, 0),
        (0.88, 1),
        (0.91, 1),
        (0.92, 2),
        (0.93, 2),
        (0.94, 3),
        (0.955, 3),
        (0.96, 4),
        (0.99, 4),
    ],
)
def test_ladder_entry_thresholds(guard, sampler, vram, expected_level):
    feed_steady(guard, sampler, vram)
    assert guard.degradation_level == expected_level


# --- hysteresis (no flapping) ----------------------------------------------


def test_hysteresis_holds_level_until_margin_cleared(guard, sampler):
    # Climb to level 4.
    feed_steady(guard, sampler, 0.97)
    assert guard.degradation_level == 4

    # Drop to 0.93: below the L4 entry (0.96) but still above L4's exit
    # (0.96 - 0.06 = 0.90). Hysteresis must HOLD the level at 4 rather than
    # follow the raw usage down to level 2 — that stickiness is what stops flapping.
    feed_steady(guard, sampler, 0.93)
    assert guard.degradation_level == 4

    # Fall below the L4 exit margin: now it may step down (cascading through the
    # exit thresholds) to the level the usage actually warrants.
    feed_steady(guard, sampler, 0.895)
    assert guard.degradation_level == 3


def test_hysteresis_no_flap_on_boundary(guard, sampler):
    # Sit exactly at an entry threshold, then dip a hair below it.
    feed_steady(guard, sampler, 0.92)  # -> level 2
    assert guard.degradation_level == 2
    feed_steady(guard, sampler, 0.90)  # above L2 exit (0.86); stays at 2
    assert guard.degradation_level == 2
    feed_steady(guard, sampler, 0.85)  # below L2 exit(0.86) and L1 exit(0.82)? 0.85>=0.82
    # 0.85 < L1 entry(0.88) but >= L1 exit(0.82) → holds at level 1
    assert guard.degradation_level == 1
    feed_steady(guard, sampler, 0.80)  # below all exits → normal
    assert guard.degradation_level == 0


def test_recovery_is_hysteretic_not_instant(guard, sampler):
    feed_steady(guard, sampler, 0.89)  # level 1
    assert guard.degradation_level == 1
    # Drop to just above L1 exit (0.82): must stay at 1.
    feed_steady(guard, sampler, 0.83)
    assert guard.degradation_level == 1
    # Drop below the exit margin: recover to 0.
    feed_steady(guard, sampler, 0.81)
    assert guard.degradation_level == 0


# --- spike suppression via rolling window ----------------------------------


def test_single_spike_does_not_trip_degradation(guard, sampler):
    # Steady low usage, then ONE high spike. Window=3 → mean stays low.
    feed_steady(guard, sampler, 0.40)
    assert guard.degradation_level == 0
    sampler.ratios["vram"] = 0.99
    guard.feed(sampler.sample())  # one spike among low samples
    # mean of (0.40, 0.40, 0.99) ≈ 0.60 → still normal.
    assert guard.degradation_level == 0


def test_sustained_pressure_does_trip(guard, sampler):
    for _ in range(5):
        sampler.ratios["vram"] = 0.99
        guard.feed(sampler.sample())
    assert guard.degradation_level == 4


# --- admission control: cold path ------------------------------------------


async def test_cold_admitted_when_normal(guard, sampler):
    feed_steady(guard, sampler, 0.50)
    adm = await guard.acquire(ResourceEstimate(vram_gb=1.0), "cold")
    assert adm.kind == "full"


async def test_cold_deferred_under_any_degradation(guard, sampler):
    feed_steady(guard, sampler, 0.89)  # level 1
    adm = await guard.acquire(ResourceEstimate(vram_gb=1.0), "cold")
    assert adm.kind == "defer"


async def test_cold_deferred_when_op_would_cross_ceiling(guard, sampler):
    feed_steady(guard, sampler, 0.80)  # level 0, but a big op would cross
    # 0.80 + 4GB/16GB(=0.25) = 1.05 > 0.96 ceiling.
    adm = await guard.acquire(ResourceEstimate(vram_gb=4.0), "cold")
    assert adm.kind == "defer"


# --- anti-starvation: deferral is a delay, never a silent drop --------------


async def test_cold_admitted_once_it_outwaits_the_defer_budget(guard, sampler, settings):
    """A host whose *idle* peak sits above ladder_l1 never de-escalates, so an
    unbounded defer means the job is never scored. Past the budget it must run."""
    feed_steady(guard, sampler, 0.89)  # level 1, and it will stay there
    fresh = await guard.acquire(ResourceEstimate(vram_gb=1.0), "cold")
    assert fresh.kind == "defer"

    starved = await guard.acquire(
        ResourceEstimate(vram_gb=1.0, waited_s=settings.coldpath_max_defer_s), "cold"
    )
    assert starved.allowed
    assert "deferred" in starved.reason


async def test_starved_cold_job_still_stops_at_the_hard_ceiling(guard, sampler):
    """Out-waiting the soft ladder must not buy passage through the 96% ceiling —
    that is the freeze protection, not a load-shedding preference."""
    feed_steady(guard, sampler, 0.80)
    adm = await guard.acquire(
        ResourceEstimate(vram_gb=4.0, waited_s=10_000.0), "cold"  # would project to 1.05
    )
    assert adm.kind == "defer"


async def test_cold_defer_budget_is_not_reached_early(guard, sampler, settings):
    feed_steady(guard, sampler, 0.89)
    adm = await guard.acquire(
        ResourceEstimate(vram_gb=1.0, waited_s=settings.coldpath_max_defer_s - 0.1), "cold"
    )
    assert adm.kind == "defer"


# --- admission control: hot path -------------------------------------------


async def test_hot_never_blocks_the_live_turn(guard, sampler):
    for vram in (0.50, 0.89, 0.93, 0.95, 0.99):
        feed_steady(guard, sampler, vram)
        adm = await guard.acquire(
            ResourceEstimate(vram_gb=0.3, llm_max_tokens=512), "hot"
        )
        assert adm.kind in ("full", "degraded"), f"hot blocked at vram={vram}"


async def test_hot_degrades_llm_params_at_level_2(guard, sampler):
    feed_steady(guard, sampler, 0.92)  # level 2
    adm = await guard.acquire(
        ResourceEstimate(vram_gb=0.3, llm_max_tokens=512, llm_context=4096), "hot"
    )
    assert adm.kind == "degraded"
    assert adm.params["max_tokens"] < 512
    assert adm.params["context"] < 4096


async def test_hot_new_session_rejected_at_ceiling(guard, sampler):
    feed_steady(guard, sampler, 0.97)  # level 4
    adm = await guard.acquire(
        ResourceEstimate(vram_gb=0.3, is_new_session=True), "hot"
    )
    assert adm.kind == "reject"


async def test_hot_existing_turn_protected_at_ceiling(guard, sampler):
    feed_steady(guard, sampler, 0.97)  # level 4
    adm = await guard.acquire(
        ResourceEstimate(vram_gb=0.3, is_new_session=False, llm_max_tokens=512), "hot"
    )
    # The in-flight learner is NOT cut off — degraded, not rejected.
    assert adm.kind == "degraded"


# --- projection & headroom -------------------------------------------------


def test_headroom(guard, sampler):
    feed_steady(guard, sampler, 0.70)
    assert guard.headroom("vram") == pytest.approx(0.30, abs=1e-6)


def test_project_scales_vram_by_total(guard, sampler):
    feed_steady(guard, sampler, 0.50)
    proj = guard._project(ResourceEstimate(vram_gb=1.6))  # 1.6/16 = 0.10
    assert proj["vram"] == pytest.approx(0.60, abs=1e-6)


# --- startup budget --------------------------------------------------------


def test_startup_budget_fits(guard, sampler):
    feed_steady(guard, sampler, 0.05)  # near-idle baseline
    ok, msg = guard.check_startup_budget(min_vram_gb=2.0)
    assert ok
    assert "FITS" in msg


def test_startup_budget_rejects_oversized_set(guard, sampler):
    feed_steady(guard, sampler, 0.05)
    ok, msg = guard.check_startup_budget(min_vram_gb=10.0)  # + vLLM 68% ⇒ overflows
    assert not ok
    assert "DOES NOT FIT" in msg


# --- CPU-only host degrades sanely -----------------------------------------


def test_cpu_only_host_runs_without_gpu(settings):
    cpu_sampler = FakeSampler(gpu=False)
    g = ResourceGuard(sampler=cpu_sampler, settings=settings)
    g.feed(cpu_sampler.sample())
    assert g.snapshot().get("vram") is None
    ok, msg = g.check_startup_budget(min_vram_gb=8.0)
    assert ok  # no GPU ⇒ VRAM budget N/A, CPU fallbacks apply
    assert "no GPU" in msg


# --- background sampler ----------------------------------------------------


async def test_background_sampler_runs_and_stops(settings):
    settings = settings.model_copy(update={"sample_interval_s": 0.01})
    s = FakeSampler()
    g = ResourceGuard(sampler=s, settings=settings)
    await g.start()
    await asyncio.sleep(0.05)
    await g.stop()
    assert len(g._window) >= 1  # took at least the seed sample


# --- sampler cost (guard must be cheap) ------------------------------------


def test_real_sampler_is_cheap():
    """The guard's own sample must be far under the 1s interval."""
    from time import perf_counter

    sampler = PsutilNvmlSampler(disk_path=".")
    sampler.sample()  # warm up
    t0 = perf_counter()
    for _ in range(20):
        sampler.sample()
    avg = (perf_counter() - t0) / 20
    assert avg < 0.1, f"sample too slow: {avg*1000:.1f}ms"
    if hasattr(sampler, "shutdown"):
        sampler.shutdown()
