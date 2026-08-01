"""End-to-end API tests for per-user profiles, sessions, assessments, progress.

Uses the real app (lifespan boots the guard + a temp SQLite DB configured in
conftest). Each test uses a unique user_id so the shared test DB stays conflict-free.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.coldpath.scoring import DIMENSIONS
from backend.core.util import new_id
from backend.main import app


def _uid() -> str:
    return "u" + new_id()[:10]


def test_user_crud_flow():
    with TestClient(app) as client:
        uid = _uid()
        r = client.post("/users", json={"user_id": uid, "display_name": "Test One"})
        assert r.status_code == 201, r.text
        assert r.json()["user_id"] == uid

        # duplicate → 409
        assert client.post("/users", json={"user_id": uid, "display_name": "x"}).status_code == 409

        assert client.get(f"/users/{uid}").json()["display_name"] == "Test One"

        r = client.patch(f"/users/{uid}", json={"display_name": "Renamed", "current_level": 3})
        assert r.json()["display_name"] == "Renamed"
        assert r.json()["current_level"] == 3

        assert client.get("/users").status_code == 200
        assert client.delete(f"/users/{uid}").status_code == 204
        assert client.get(f"/users/{uid}").status_code == 404


def test_invalid_user_id_rejected():
    with TestClient(app) as client:
        r = client.post("/users", json={"user_id": "Has Spaces!", "display_name": "x"})
        assert r.status_code == 422


def test_session_assessment_and_progress_flow():
    with TestClient(app) as client:
        uid = _uid()
        client.post("/users", json={"user_id": uid, "display_name": "Learner"})

        r = client.post(f"/users/{uid}/sessions", json={"mode": "interview", "difficulty": 0.5})
        assert r.status_code == 201, r.text
        sid = r.json()["session_id"]

        client.post(f"/sessions/{sid}/utterances", json={"role": "learner", "transcript": "Hello"})

        scores = dict.fromkeys(DIMENSIONS, 80.0)
        r = client.post(f"/sessions/{sid}/assessments", json={"scores": scores})
        assert r.status_code == 201, r.text
        assert r.json()["overall"] == 80.0
        assert r.json()["scoring_model_version"] == "v1"

        # Recording an assessment advances the user's headline level (80 → level 3).
        assert client.get(f"/users/{uid}").json()["current_level"] == 3

        client.post(f"/sessions/{sid}/end")

        ov = client.get(f"/users/{uid}/progress").json()
        assert ov["assessments_count"] == 1
        assert ov["latest_overall"] == 80.0
        assert ov["streak_days"] == 1  # one practice day

        trend = client.get(f"/users/{uid}/progress/trend", params={"skill": "overall"}).json()
        assert len(trend) == 1 and trend[0]["value"] == 80.0


def test_assessment_rejects_unknown_dimension():
    with TestClient(app) as client:
        uid = _uid()
        client.post("/users", json={"user_id": uid, "display_name": "L"})
        sid = client.post(f"/users/{uid}/sessions", json={}).json()["session_id"]
        r = client.post(f"/sessions/{sid}/assessments", json={"scores": {"bogus": 50}})
        assert r.status_code == 422


def test_session_for_missing_user_404():
    with TestClient(app) as client:
        assert client.post("/users/ghost/sessions", json={}).status_code == 404


def test_progress_missing_user_404():
    with TestClient(app) as client:
        assert client.get("/users/ghost/progress").status_code == 404


def test_level_is_chosen_by_the_learner_not_defaulted():
    """current_level 0 means "Beginner"; it must not also mean "never asked"."""
    with TestClient(app) as client:
        uid = _uid()
        created = client.post("/users", json={"user_id": uid, "display_name": "New"}).json()
        assert created["level_selected"] is False, "a fresh profile has not chosen yet"

        chosen = client.post(f"/users/{uid}/level", json={"current_level": 0}).json()
        assert chosen["current_level"] == 0
        assert chosen["level_selected"] is True, "choosing Beginner is still choosing"


def test_scoring_advancing_a_level_does_not_count_as_choosing():
    """A PATCH from the scoring pipeline must not silence the prompt."""
    with TestClient(app) as client:
        uid = _uid()
        client.post("/users", json={"user_id": uid, "display_name": "New"})
        patched = client.patch(f"/users/{uid}", json={"current_level": 3}).json()
        assert patched["current_level"] == 3
        assert patched["level_selected"] is False
