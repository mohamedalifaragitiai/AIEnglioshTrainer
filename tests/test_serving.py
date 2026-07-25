"""Tests for the model registry: guard-gated startup budget, status lifecycle."""

from __future__ import annotations

import pytest

from backend.serving.base import (
    ManagedModel,
    ModelKind,
    ModelRegistry,
    ModelStatus,
    StartupBudgetError,
)
from tests.conftest import FakeSampler


class FakeModel(ManagedModel):
    def __init__(self, name, kind, *, device="cuda", vram_gb=1.0, available=True, fail=False):
        super().__init__(name, device=device, vram_gb=vram_gb)
        self.kind = kind
        self._available = available
        self._fail = fail
        self.loaded = False

    def available(self) -> bool:
        return self._available

    async def _load(self) -> None:
        if self._fail:
            raise RuntimeError("boom")
        self.loaded = True


def _guard_with_vram(settings, ratio: float):
    from backend.core.resource_guard import ResourceGuard

    sampler = FakeSampler()
    sampler.ratios["vram"] = ratio
    guard = ResourceGuard(sampler=sampler, settings=settings)
    guard.feed(sampler.sample())
    return guard


# --- min-set accounting ----------------------------------------------------


def test_min_set_excludes_llm_and_cpu(settings):
    guard = _guard_with_vram(settings, 0.05)
    reg = ModelRegistry(guard)
    reg.register(FakeModel("llm", ModelKind.LLM, device="cuda:vllm", vram_gb=10))  # excluded
    reg.register(FakeModel("tts-cpu", ModelKind.TTS, device="cpu", vram_gb=1))     # excluded
    reg.register(FakeModel("stt", ModelKind.STT, device="cuda", vram_gb=2))        # counts
    reg.register(FakeModel("gop", ModelKind.GOP, device="cuda", vram_gb=2))        # counts
    assert reg.min_set_vram_gb() == pytest.approx(4.0)


# --- startup budget refusal ------------------------------------------------


async def test_load_all_refuses_when_min_set_too_big(settings):
    guard = _guard_with_vram(settings, 0.05)  # low baseline
    reg = ModelRegistry(guard)
    # vLLM reserves 0.68*16≈10.9GB; a 10GB resident set overflows the 96% ceiling.
    reg.register(FakeModel("stt", ModelKind.STT, device="cuda", vram_gb=10.0))
    with pytest.raises(StartupBudgetError):
        await reg.load_all()


async def test_load_all_loads_when_fits(settings):
    guard = _guard_with_vram(settings, 0.03)
    reg = ModelRegistry(guard)
    reg.register(FakeModel("stt", ModelKind.STT, device="cuda", vram_gb=2.0))
    reg.register(FakeModel("tts", ModelKind.TTS, device="cuda", vram_gb=1.0))
    await reg.load_all()
    assert all(m.status == ModelStatus.LOADED for m in reg.models)


# --- per-model status lifecycle --------------------------------------------


async def test_unavailable_model_does_not_crash_startup(settings):
    guard = _guard_with_vram(settings, 0.03)
    reg = ModelRegistry(guard)
    reg.register(FakeModel("stt", ModelKind.STT, vram_gb=2.0, available=False))
    await reg.load_all()  # must not raise
    assert reg.models[0].status == ModelStatus.UNAVAILABLE


async def test_failed_load_propagates(settings):
    guard = _guard_with_vram(settings, 0.03)
    reg = ModelRegistry(guard)
    reg.register(FakeModel("gop", ModelKind.GOP, vram_gb=2.0, fail=True))
    with pytest.raises(RuntimeError, match="boom"):
        await reg.load_all()
    assert reg.models[0].status == ModelStatus.FAILED


async def test_disabled_model_reports_disabled(settings):
    guard = _guard_with_vram(settings, 0.03)
    reg = ModelRegistry(guard)
    m = FakeModel("stt", ModelKind.STT, vram_gb=2.0)
    m.enabled = False
    m.status = ModelStatus.DISABLED
    reg.register(m)
    await reg.load_all()
    assert reg.models[0].status == ModelStatus.DISABLED


def test_budget_report_shape(settings):
    guard = _guard_with_vram(settings, 0.05)
    reg = ModelRegistry(guard)
    reg.register(FakeModel("stt", ModelKind.STT, vram_gb=2.0))
    b = reg.budget()
    assert set(b) == {"min_set_vram_gb", "fits", "detail"}
    assert b["min_set_vram_gb"] == pytest.approx(2.0)


# --- default registry factory ----------------------------------------------


def test_default_registry_has_full_split_model_set(settings):
    from backend.serving.adapters import build_default_registry

    guard = _guard_with_vram(settings, 0.05)
    reg, client = build_default_registry(guard, settings)
    kinds = [m.kind for m in reg.models]
    assert kinds.count(ModelKind.LLM) == 2  # hot 8B + cold 14B
    assert ModelKind.STT in kinds and ModelKind.GOP in kinds and ModelKind.TTS in kinds
    # LLMs excluded from the resident min-set sum.
    assert reg.min_set_vram_gb() == pytest.approx(
        settings.stt_vram_gb + settings.gop_vram_gb + settings.tts_vram_gb
    )
