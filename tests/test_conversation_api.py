"""Per-conversation and across-conversation analysis."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.core.util import new_id
from backend.main import app


def _uid() -> str:
    return "c" + new_id()[:10]


def _conversation(client: TestClient, uid: str, *, scores: dict) -> str:
    """A session with one learner turn, one coach turn, and a recorded score."""
    sid = client.post(f"/users/{uid}/sessions", json={"mode": "free"}).json()["session_id"]
    utt = client.post(
        f"/sessions/{sid}/utterances",
        json={"role": "learner", "transcript": "I go to school yesterday"},
    ).json()
    client.post(
        f"/sessions/{sid}/utterances",
        json={"role": "coach", "transcript": "You mean you went to school yesterday."},
    )
    client.post(
        f"/sessions/{sid}/assessments",
        json={"scores": scores, "utterance_id": utt["utterance_id"]},
    )
    client.post(f"/sessions/{sid}/end")
    return sid


def test_conversation_report_has_turns_scores_and_recommendations():
    with TestClient(app) as client:
        uid = _uid()
        client.post("/users", json={"user_id": uid, "display_name": "Conv"})
        sid = _conversation(
            client, uid, scores={"grammar": 45.0, "fluency": 52.0, "vocabulary": 80.0}
        )

        r = client.get(f"/users/{uid}/conversations/{sid}")
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["session_id"] == sid and body["user_id"] == uid
        assert body["learner_turns"] == 1
        assert len(body["turns"]) == 2
        assert body["turns"][0]["transcript"] == "I go to school yesterday"
        assert body["turns"][0]["scores"]["grammar"] == 45.0
        assert body["words_spoken"] == 5
        assert body["overall"] is not None

        # The weakest skills drive concrete advice, worst first.
        assert body["weaknesses"][0] == "grammar"
        assert body["recommendations"][0]["skill"] == "grammar"
        assert body["recommendations"][0]["priority"] == "high"
        assert body["recommendations"][0]["actions"], "advice must be actionable, not a label"
        assert "vocabulary" in body["strengths"]


def test_conversation_list_and_full_analysis_agree():
    with TestClient(app) as client:
        uid = _uid()
        client.post("/users", json={"user_id": uid, "display_name": "Conv"})
        _conversation(client, uid, scores={"grammar": 40.0})
        _conversation(client, uid, scores={"grammar": 70.0})

        rows = client.get(f"/users/{uid}/conversations").json()
        assert len(rows) == 2
        assert all(r["preview"] for r in rows)

        analysis = client.get(f"/users/{uid}/analysis").json()
        assert analysis["conversations"] == 2
        assert analysis["learner_turns"] == 2
        # Both views are built from the same rows, so their averages must match.
        assert analysis["overall"] == round(
            sum(r["overall"] for r in rows) / len(rows), 1
        )


def test_trend_is_measured_not_asserted():
    with TestClient(app) as client:
        uid = _uid()
        client.post("/users", json={"user_id": uid, "display_name": "Conv"})
        for score in (30.0, 35.0, 80.0, 85.0):
            _conversation(client, uid, scores={"grammar": score})

        analysis = client.get(f"/users/{uid}/analysis").json()
        assert analysis["trend"]["direction"] == "improving"
        assert analysis["trend"]["delta"] > 0
        assert analysis["best_conversation"]["overall"] >= analysis["overall"]


def test_a_conversation_belonging_to_someone_else_is_not_readable():
    """The session id is opaque, so the path cannot be trusted to name the owner."""
    with TestClient(app) as client:
        mine, theirs = _uid(), _uid()
        for u in (mine, theirs):
            client.post("/users", json={"user_id": u, "display_name": "x"})
        sid = _conversation(client, theirs, scores={"grammar": 50.0})
        assert client.get(f"/users/{mine}/conversations/{sid}").status_code == 404


def test_unscored_conversation_still_renders():
    """Scoring is deferred under load; the report must say so, not fail."""
    with TestClient(app) as client:
        uid = _uid()
        client.post("/users", json={"user_id": uid, "display_name": "Conv"})
        sid = client.post(f"/users/{uid}/sessions", json={"mode": "free"}).json()["session_id"]
        client.post(
            f"/sessions/{sid}/utterances",
            json={"role": "learner", "transcript": "hello there coach"},
        )

        body = client.get(f"/users/{uid}/conversations/{sid}").json()
        assert body["overall"] is None
        assert body["scores"] == {}
        assert body["pending_scoring"] is True
        assert body["turns"][0]["transcript"] == "hello there coach"
