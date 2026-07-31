"""Signup / login, and what changes when COACH_AUTH_REQUIRED is on.

Enforcement is toggled on the *cached* Settings instance rather than through the
environment: ``backend.main`` reads ``get_settings()`` once at import and the
middleware closes over that object, so mutating the singleton is what actually
flips behaviour for a running app. The context manager always restores it — a
leaked ``auth_required=True`` would fail every other API test in the suite.
"""

from __future__ import annotations

import contextlib
import json

import pytest
from fastapi.testclient import TestClient

from backend.core.util import new_id
from backend.main import app
from config.settings import get_settings

PASSWORD = "correct horse battery"


def _uid() -> str:
    return "a" + new_id()[:10]


@contextlib.contextmanager
def auth_enforced():
    settings = get_settings()
    settings.auth_required = True
    try:
        yield
    finally:
        settings.auth_required = False


def _signup(client: TestClient, uid: str, password: str = PASSWORD):
    return client.post(
        "/auth/signup",
        json={"user_id": uid, "display_name": "Auth Test", "password": password},
    )


# --- signup / login basics -------------------------------------------------


def test_signup_then_me_then_logout():
    with TestClient(app) as client:
        uid = _uid()
        r = _signup(client, uid)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["user"]["user_id"] == uid
        assert body["token"] and body["expires_at"]

        auth = {"Authorization": f"Bearer {body['token']}"}
        assert client.get("/auth/me", headers=auth).json()["user_id"] == uid

        assert client.post("/auth/logout", headers=auth).status_code == 204
        # The token is dead, and TestClient kept the cookie — neither works now.
        client.cookies.clear()
        assert client.get("/auth/me", headers=auth).status_code == 401


def test_login_rejects_wrong_password_and_unknown_user():
    with TestClient(app) as client:
        uid = _uid()
        _signup(client, uid)

        bad = client.post("/auth/login", json={"user_id": uid, "password": "not it"})
        assert bad.status_code == 401
        missing = client.post("/auth/login", json={"user_id": _uid(), "password": PASSWORD})
        assert missing.status_code == 401
        # Same wording either way: the reply must not confirm which ids exist.
        assert bad.json()["detail"] == missing.json()["detail"]

        good = client.post("/auth/login", json={"user_id": uid, "password": PASSWORD})
        assert good.status_code == 200
        assert good.json()["user"]["user_id"] == uid


def test_password_is_never_stored_in_the_clear():
    with TestClient(app) as client:
        uid = _uid()
        _signup(client, uid)
        db = app.state.db
        with db.connection() as con:
            row = con.execute(
                "SELECT algo, iterations, salt, digest FROM user_credentials WHERE user_id=?",
                (uid,),
            ).fetchone()
        assert row is not None
        assert PASSWORD not in json.dumps(dict(row))
        assert row["algo"] == "pbkdf2_sha256"


def test_session_token_is_stored_only_as_a_fingerprint():
    with TestClient(app) as client:
        token = _signup(client, _uid()).json()["token"]
        with app.state.db.connection() as con:
            rows = con.execute("SELECT token_hash FROM auth_sessions").fetchall()
        assert all(r["token_hash"] != token for r in rows)


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"user_id": "Has Spaces!", "display_name": "x", "password": PASSWORD}, 422),
        ({"user_id": "shortpw_user", "display_name": "x", "password": "abc"}, 422),
    ],
)
def test_signup_validation(payload, expected):
    with TestClient(app) as client:
        assert client.post("/auth/signup", json=payload).status_code == expected


def test_an_email_works_as_a_learner_id():
    """People reach for their email at a login screen — and did, then got a 401."""
    with TestClient(app) as client:
        email = f"{_uid()}@example.com"
        assert _signup(client, email).status_code == 201
        # And capitalisation on the way back in is not a wrong password.
        r = client.post("/auth/login", json={"user_id": email.upper(), "password": PASSWORD})
        assert r.status_code == 200
        assert r.json()["user"]["user_id"] == email


def test_ids_that_would_escape_the_report_directory_are_still_refused():
    """`user_id` is interpolated into a report filename in coldpath/insights.py."""
    with TestClient(app) as client:
        for bad in ("../etc/passwd", "..", "a/b", "a\\b", "c:evil", "Has Spaces!"):
            r = client.post(
                "/auth/signup",
                json={"user_id": bad, "display_name": "x", "password": PASSWORD},
            )
            assert r.status_code == 422, f"{bad!r} was accepted"


def test_second_signup_for_the_same_account_conflicts():
    with TestClient(app) as client:
        uid = _uid()
        assert _signup(client, uid).status_code == 201
        assert _signup(client, uid).status_code == 409


def test_signup_claims_a_credential_less_profile_and_keeps_its_history():
    """The seeded demo learner predates auth; signing up must adopt it, not fail."""
    with TestClient(app) as client:
        uid = _uid()
        assert client.post(
            "/users", json={"user_id": uid, "display_name": "Legacy Profile"}
        ).status_code == 201
        created_at = client.get(f"/users/{uid}").json()["created_at"]

        r = _signup(client, uid)
        assert r.status_code == 201, r.text
        # Same profile row — not a replacement.
        assert r.json()["user"]["created_at"] == created_at
        assert r.json()["user"]["display_name"] == "Auth Test"
        login = client.post("/auth/login", json={"user_id": uid, "password": PASSWORD})
        assert login.status_code == 200


# --- enforcement -----------------------------------------------------------


def test_api_is_anonymous_while_auth_is_off():
    with TestClient(app) as client:
        uid = _uid()
        _signup(client, uid)
        client.cookies.clear()
        assert client.get(f"/users/{uid}").status_code == 200
        assert client.get("/auth/status").json()["auth_required"] is False


def test_enforced_api_requires_a_token():
    with TestClient(app) as client:
        uid = _uid()
        token = _signup(client, uid).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        client.cookies.clear()

        with auth_enforced():
            assert client.get(f"/users/{uid}").status_code == 401
            assert client.get(f"/users/{uid}", headers=auth).status_code == 200
            assert client.get(f"/users/{uid}/progress", headers=auth).status_code == 200
            # Ops endpoints stay open — they carry no learner data and the
            # dashboards scrape them unauthenticated.
            assert client.get("/healthz").status_code == 200
            assert client.get("/metrics").status_code == 200
            status = client.get("/auth/status", headers=auth).json()
            assert status["auth_required"] is True and status["user_id"] == uid


def test_enforced_api_refuses_another_learners_profile():
    with TestClient(app) as client:
        mine, theirs = _uid(), _uid()
        token = _signup(client, mine).json()["token"]
        _signup(client, theirs)
        auth = {"Authorization": f"Bearer {token}"}
        client.cookies.clear()

        with auth_enforced():
            assert client.get(f"/users/{theirs}", headers=auth).status_code == 403
            assert client.get(f"/users/{theirs}/assessments", headers=auth).status_code == 403
            # The picker must not double as a roster of everyone else.
            listed = client.get("/users", headers=auth).json()
            assert [u["user_id"] for u in listed] == [mine]
            # Accounts come from signup once auth is on.
            assert client.post(
                "/users", headers=auth, json={"user_id": _uid(), "display_name": "x"}
            ).status_code == 403


def test_revoked_token_stops_working():
    with TestClient(app) as client:
        uid = _uid()
        token = _signup(client, uid).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        client.post("/auth/logout", headers=auth)
        client.cookies.clear()
        with auth_enforced():
            assert client.get(f"/users/{uid}", headers=auth).status_code == 401


# --- the live WebSocket ----------------------------------------------------


def test_ws_rejects_missing_and_mismatched_tokens():
    with TestClient(app) as client:
        mine, theirs = _uid(), _uid()
        token = _signup(client, mine).json()["token"]
        _signup(client, theirs)
        client.cookies.clear()

        with auth_enforced():
            with client.websocket_connect(f"/ws/session?user_id={mine}") as ws:
                assert ws.receive_json()["type"] == "error"
                # 4401: authenticated the same way HTTP does, reported in the
                # close code because a WebSocket has no status line.
                assert ws.receive()["code"] == 4401

            url = f"/ws/session?user_id={theirs}&token={token}"
            with client.websocket_connect(url) as ws:
                assert ws.receive_json()["type"] == "error"
                assert ws.receive()["code"] == 4403


def test_ws_accepts_a_valid_token():
    with TestClient(app) as client:
        uid = _uid()
        token = _signup(client, uid).json()["token"]
        client.cookies.clear()
        with auth_enforced():
            url = f"/ws/session?user_id={uid}&token={token}&ptt=1"
            with client.websocket_connect(url) as ws:
                ws.send_text(json.dumps({"type": "bye"}))
