"""End-to-end API tests for per-user profiles, sessions, assessments, progress.

Uses the real app (lifespan boots the guard + a temp SQLite DB configured in
conftest). Each test uses a unique user_id so the shared test DB stays conflict-free.

Every user-scoped route is gated on a bearer token for that same user, so these tests
register through ``/auth/register`` and pass the resulting header — see
``tests/test_auth.py`` for the auth behaviour itself.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.coldpath.scoring import DIMENSIONS
from backend.core.util import new_id
from backend.main import app
from tests.conftest import register_user


def _uid() -> str:
    return "u" + new_id()[:10]


def test_user_crud_flow():
    with TestClient(app) as client:
        uid, h = register_user(client, _uid(), display_name="Test One")

        # a second registration of the same id → 409
        assert (
            client.post(
                "/auth/register",
                json={"user_id": uid, "display_name": "x", "password": "another pass"},
            ).status_code
            == 409
        )

        assert client.get(f"/users/{uid}", headers=h).json()["display_name"] == "Test One"

        r = client.patch(
            f"/users/{uid}", json={"display_name": "Renamed", "current_level": 3}, headers=h
        )
        assert r.json()["display_name"] == "Renamed"
        assert r.json()["current_level"] == 3

        assert client.get("/users", headers=h).status_code == 200
        assert client.delete(f"/users/{uid}", headers=h).status_code == 204
        # The profile is gone, so its token no longer resolves to anyone.
        assert client.get(f"/users/{uid}", headers=h).status_code == 401


def test_invalid_user_id_rejected():
    with TestClient(app) as client:
        r = client.post("/users", json={"user_id": "Has Spaces!", "display_name": "x"})
        assert r.status_code == 422
        r = client.post(
            "/auth/register",
            json={"user_id": "Has Spaces!", "display_name": "x", "password": "good enough"},
        )
        assert r.status_code == 422


def test_session_assessment_and_progress_flow():
    with TestClient(app) as client:
        uid, h = register_user(client, _uid(), display_name="Learner")

        r = client.post(
            f"/users/{uid}/sessions", json={"mode": "interview", "difficulty": 0.5}, headers=h
        )
        assert r.status_code == 201, r.text
        sid = r.json()["session_id"]

        client.post(
            f"/sessions/{sid}/utterances",
            json={"role": "learner", "transcript": "Hello"},
            headers=h,
        )

        scores = dict.fromkeys(DIMENSIONS, 80.0)
        r = client.post(f"/sessions/{sid}/assessments", json={"scores": scores}, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["overall"] == 80.0
        assert r.json()["scoring_model_version"] == "v1"

        # Recording an assessment advances the user's headline level (80 → level 3).
        assert client.get(f"/users/{uid}", headers=h).json()["current_level"] == 3

        client.post(f"/sessions/{sid}/end", headers=h)

        ov = client.get(f"/users/{uid}/progress", headers=h).json()
        assert ov["assessments_count"] == 1
        assert ov["latest_overall"] == 80.0
        assert ov["streak_days"] == 1  # one practice day

        trend = client.get(
            f"/users/{uid}/progress/trend", params={"skill": "overall"}, headers=h
        ).json()
        assert len(trend) == 1 and trend[0]["value"] == 80.0


def test_assessment_rejects_unknown_dimension():
    with TestClient(app) as client:
        uid, h = register_user(client, _uid(), display_name="L")
        sid = client.post(f"/users/{uid}/sessions", json={}, headers=h).json()["session_id"]
        r = client.post(f"/sessions/{sid}/assessments", json={"scores": {"bogus": 50}}, headers=h)
        assert r.status_code == 422


def test_session_for_missing_user_404():
    with TestClient(app) as client:
        _, h = register_user(client, _uid())
        # Someone else's (or a nonexistent) user id is indistinguishable: both 404.
        assert client.post("/users/ghost/sessions", json={}, headers=h).status_code == 404


def test_progress_missing_user_404():
    with TestClient(app) as client:
        _, h = register_user(client, _uid())
        assert client.get("/users/ghost/progress", headers=h).status_code == 404


def test_user_routes_require_a_token():
    """Regression guard: private history must never be readable unauthenticated."""
    with TestClient(app) as client:
        uid, h = register_user(client, _uid())
        for path in (
            f"/users/{uid}",
            f"/users/{uid}/progress",
            f"/users/{uid}/assessments",
            f"/users/{uid}/sessions",
            f"/users/{uid}/gaps",
            f"/users/{uid}/plan",
            f"/users/{uid}/feedback",
        ):
            assert client.get(path).status_code == 401, path
            assert client.get(path, headers=h).status_code == 200, path
