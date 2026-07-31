"""The admin cohort view: who can read it, and whether the numbers are right."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.core.util import new_id
from backend.main import app
from tests.test_auth import PASSWORD, _make_admin, _signup, _uid


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_admin_overview_reports_the_whole_cohort():
    with TestClient(app) as client:
        boss = _uid()
        boss_token = _signup(client, boss).json()["token"]
        _make_admin(boss)

        learner = "l" + new_id()[:9]
        client.post("/users", json={"user_id": learner, "display_name": "Learner"})
        client.post(f"/dev/users/{learner}/seed-demo")

        body = client.get("/admin/overview", headers=_auth(boss_token)).json()

        totals = body["totals"]
        assert totals["users"] >= 2
        assert totals["assessments"] >= 6
        assert totals["admins"] >= 1

        row = next(u for u in body["users"] if u["user_id"] == learner)
        assert row["assessments"] == 6           # seed_demo writes six
        assert row["display_name"] == "Learner"
        assert row["is_admin"] is False
        assert row["has_password"] is False      # created via POST /users, never signed up
        assert row["last_active"] is not None
        assert 0 <= row["avg_overall"] <= 100
        assert row["avg_scores"], "per-dimension averages should be populated"

        me = next(u for u in body["users"] if u["user_id"] == boss)
        assert me["is_admin"] is True and me["has_password"] is True


def test_overview_is_refused_to_learners_and_to_anonymous_callers():
    """These rows are everyone's history — the check cannot depend on
    COACH_AUTH_REQUIRED being on."""
    with TestClient(app) as client:
        learner = _uid()
        token = _signup(client, learner).json()["token"]
        client.cookies.clear()

        # auth_required is OFF in the test env: still 401/403, not 200.
        assert client.get("/admin/overview").status_code == 401
        assert client.get("/admin/overview", headers=_auth(token)).status_code == 403


def test_counts_move_when_a_learner_is_added():
    with TestClient(app) as client:
        boss = _uid()
        boss_token = _signup(client, boss).json()["token"]
        _make_admin(boss)

        before = client.get("/admin/overview", headers=_auth(boss_token)).json()["totals"]["users"]
        _signup(client, _uid(), PASSWORD)
        after = client.get("/admin/overview", headers=_auth(boss_token)).json()["totals"]["users"]
        assert after == before + 1


def test_a_learner_who_never_practised_is_counted_as_such():
    with TestClient(app) as client:
        boss = _uid()
        boss_token = _signup(client, boss).json()["token"]
        _make_admin(boss)

        idle = _uid()
        _signup(client, idle)
        body = client.get("/admin/overview", headers=_auth(boss_token)).json()
        row = next(u for u in body["users"] if u["user_id"] == idle)
        assert row["last_active"] is None
        assert row["assessments"] == 0
        assert row["avg_scores"] == {}
        assert body["totals"]["never_practised"] >= 1
