"""API smoke tests — the app boots the guard, exposes metrics and health."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def test_healthz():
    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_metrics_exposes_guard_series():
    with TestClient(app) as client:
        r = client.get("/metrics")
        assert r.status_code == 200
        body = r.text
        # The guard's required metrics must be present from the first commit.
        assert "degradation_level" in body
        assert "guard_sample_duration_seconds" in body
        assert "resource_usage_ratio" in body


def test_guard_endpoint_reports_state():
    with TestClient(app) as client:
        r = client.get("/guard")
        assert r.status_code == 200
        data = r.json()
        assert data["degradation_level"] in (0, 1, 2, 3, 4)
        assert data["ceiling"] == 0.96
        assert "usage" in data
