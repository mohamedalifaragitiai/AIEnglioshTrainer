"""API tests for the Phase 5 insights endpoints (via the real app)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.core.util import new_id
from backend.main import app


def _seeded_user(client) -> str:
    uid = "i" + new_id()[:8]
    client.post("/users", json={"user_id": uid, "display_name": "Insights"})
    client.post(f"/dev/users/{uid}/seed-demo")
    return uid


def test_gaps_endpoint_ranked():
    with TestClient(app) as client:
        uid = _seeded_user(client)
        gaps = client.get(f"/users/{uid}/gaps").json()
        assert len(gaps) == 8
        assert gaps[0]["rank"] == 1
        assert gaps[0]["severity"] >= gaps[-1]["severity"]


def test_plan_and_feedback_endpoints():
    with TestClient(app) as client:
        uid = _seeded_user(client)
        plan = client.get(f"/users/{uid}/plan").json()
        assert 0.0 <= plan["difficulty"] <= 1.0
        assert plan["focus_areas"]

        created = client.post(f"/users/{uid}/plan").json()
        assert created["summary"]

        fb = client.get(f"/users/{uid}/feedback").json()
        assert fb["current_level"] >= 1


def test_improvement_and_snapshot():
    with TestClient(app) as client:
        uid = _seeded_user(client)
        imp = client.get(f"/users/{uid}/gaps/improvement?days=30").json()
        assert isinstance(imp, list) and imp
        snap = client.post(f"/users/{uid}/gaps/snapshot").json()
        assert "gaps" in snap


def test_report_downloads_all_formats():
    with TestClient(app) as client:
        uid = _seeded_user(client)
        expected = {
            "json": (b"{", "application/json"),
            "csv": (b"created_at", "text/csv"),
            "xlsx": (b"PK", "application/vnd.openxmlformats"),
            "pdf": (b"%PDF-", "application/pdf"),
        }
        for fmt, (magic, ctype) in expected.items():
            r = client.get(f"/users/{uid}/report", params={"format": fmt})
            assert r.status_code == 200, (fmt, r.text)
            assert ctype in r.headers["content-type"]
            assert r.content[: len(magic)] == magic
            assert "attachment" in r.headers.get("content-disposition", "")


def test_report_bad_format_422():
    with TestClient(app) as client:
        uid = _seeded_user(client)
        assert client.get(f"/users/{uid}/report", params={"format": "docx"}).status_code == 422


def test_insights_missing_user_404():
    with TestClient(app) as client:
        assert client.get("/users/ghost/gaps").status_code == 404
        assert client.get("/users/ghost/plan").status_code == 404
