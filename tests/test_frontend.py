"""Tests for the served UI and the demo-seed convenience endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.core.util import new_id
from backend.main import app


def test_index_served():
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "AI English" in r.text


def test_seed_demo_populates_dashboard():
    with TestClient(app) as client:
        uid = "d" + new_id()[:8]
        client.post("/users", json={"user_id": uid, "display_name": "Demo"})
        ov = client.post(f"/dev/users/{uid}/seed-demo").json()
        assert ov["assessments_count"] == 6
        assert ov["current_level"] >= 1
        assert ov["streak_days"] == 6
        # Trend now has points to chart.
        trend = client.get(f"/users/{uid}/progress/trend?skill=overall&days=3650").json()
        assert len(trend) == 6


def test_seed_demo_missing_user_404():
    with TestClient(app) as client:
        assert client.post("/dev/users/ghost/seed-demo").status_code == 404
