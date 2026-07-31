"""One learner must not reach another's data — including by resource id.

The enforcement middleware can only compare a user id it can see in the path.
Everything addressed by an opaque id (a session, an utterance) went straight
past it, so a signed-in learner could read another learner's transcripts and
write into their history. These tests pin each hole shut.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
from tests.test_auth import _make_admin, _signup, _uid, auth_enforced


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _setup(client: TestClient):
    """A victim with a session and an utterance, plus an unrelated attacker."""
    victim, attacker = _uid(), _uid()
    victim_token = _signup(client, victim).json()["token"]
    attacker_token = _signup(client, attacker).json()["token"]

    session_id = client.post(
        f"/users/{victim}/sessions", headers=_auth(victim_token), json={"mode": "free"}
    ).json()["session_id"]
    utterance_id = client.post(
        f"/sessions/{session_id}/utterances",
        headers=_auth(victim_token),
        json={"role": "learner", "transcript": "my private practice sentence"},
    ).json()["utterance_id"]
    client.cookies.clear()
    return victim, victim_token, attacker, attacker_token, session_id, utterance_id


def test_a_learner_cannot_read_another_learners_session_or_transcripts():
    with TestClient(app) as client:
        _v, _vt, _a, at, sid, uid_ = _setup(client)
        with auth_enforced():
            assert client.get(f"/sessions/{sid}", headers=_auth(at)).status_code == 403
            r = client.get(f"/sessions/{sid}/utterances", headers=_auth(at))
            assert r.status_code == 403, "transcripts are the learner's own words"
            assert "private practice sentence" not in r.text
            outputs = client.get(f"/utterances/{uid_}/evaluator-outputs", headers=_auth(at))
            assert outputs.status_code == 403


def test_a_learner_cannot_write_into_another_learners_history():
    with TestClient(app) as client:
        _v, _vt, _a, at, sid, _u = _setup(client)
        with auth_enforced():
            assert (
                client.post(
                    f"/sessions/{sid}/utterances",
                    headers=_auth(at),
                    json={"role": "learner", "transcript": "injected"},
                ).status_code
                == 403
            )
            # This one also moves the victim's level.
            assert (
                client.post(
                    f"/sessions/{sid}/assessments",
                    headers=_auth(at),
                    json={"scores": {"grammar": 5.0}},
                ).status_code
                == 403
            )
            assert client.post(f"/sessions/{sid}/end", headers=_auth(at)).status_code == 403


def test_seed_demo_under_a_prefix_is_still_ownership_checked():
    """/dev/users/<id>/seed-demo — the middleware used to only look at the root."""
    with TestClient(app) as client:
        victim, _vt, _a, at, _s, _u = _setup(client)
        with auth_enforced():
            r = client.post(f"/dev/users/{victim}/seed-demo", headers=_auth(at))
            assert r.status_code == 403


def test_the_owner_still_reaches_their_own_data():
    """The fix must not lock people out of their own practice."""
    with TestClient(app) as client:
        _v, vt, _a, _at, sid, uid_ = _setup(client)
        with auth_enforced():
            assert client.get(f"/sessions/{sid}", headers=_auth(vt)).status_code == 200
            assert client.get(f"/sessions/{sid}/utterances", headers=_auth(vt)).status_code == 200
            assert (
                client.get(f"/utterances/{uid_}/evaluator-outputs", headers=_auth(vt)).status_code
                == 200
            )


def test_an_admin_reaches_everything():
    with TestClient(app) as client:
        _v, _vt, attacker, at, sid, uid_ = _setup(client)
        _make_admin(attacker)
        with auth_enforced():
            assert client.get(f"/sessions/{sid}", headers=_auth(at)).status_code == 200
            assert client.get(f"/sessions/{sid}/utterances", headers=_auth(at)).status_code == 200
            assert (
                client.get(f"/utterances/{uid_}/evaluator-outputs", headers=_auth(at)).status_code
                == 200
            )
