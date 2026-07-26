"""API tests for /models — status + budget with model loading disabled (default)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def test_models_list_reports_specs():
    from config.settings import get_settings

    with TestClient(app) as client:
        r = client.get("/models")
        assert r.status_code == 200
        models = r.json()
        # STT + GOP + TTS, plus one entry per DISTINCT served LLM: hot 8B + cold 14B
        # normally, but a single model doing double duty collapses to one entry.
        s = get_settings()
        expected_llms = 1 if s.vllm_hot_model == s.vllm_cold_model else 2
        assert len(models) == 3 + expected_llms
        # Never the same model listed twice — that double-counted models_loaded.
        names = [m["name"] for m in models]
        assert len(names) == len(set(names))
        kinds = {m["kind"] for m in models}
        assert {"llm", "stt", "gop", "tts"} <= kinds
        # Loading disabled by default → nothing loaded.
        assert all(m["status"] in ("not_loaded", "disabled") for m in models)


def test_models_budget_endpoint():
    with TestClient(app) as client:
        b = client.get("/models/budget").json()
        assert b["enabled"] is True
        assert "fits" in b and "min_set_vram_gb" in b


def test_llm_health_without_server():
    with TestClient(app) as client:
        h = client.get("/models/llm/health").json()
        assert h["configured"] is True
        assert h["healthy"] is False  # no vLLM server running in tests
