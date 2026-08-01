"""Read-aloud: passage selection and attempt scoring."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.coldpath.reading import PASSAGES, passage_for, score_reading
from backend.core.util import new_id
from backend.main import app

REFERENCE = "The market opens early on Friday and people buy fruit before the heat arrives"


def test_passage_is_deterministic_for_a_seed_but_varies_across_seeds():
    """A refresh must not swap the text out mid-attempt; a new attempt should
    not always hand back the same passage."""
    a = passage_for(1, seed="user-a")
    assert a == passage_for(1, seed="user-a")
    variants = {passage_for(1, seed=f"s{i}")["title"] for i in range(30)}
    assert len(variants) > 1 or len(PASSAGES[1]) == 1


def test_passage_level_is_clamped_not_crashed():
    assert passage_for(99)["level"] == max(PASSAGES)
    assert passage_for(-5)["level"] == 0


def test_a_perfect_read_scores_100():
    r = score_reading(REFERENCE, REFERENCE, duration_s=20.0)
    assert r["accuracy"] == 100.0
    assert r["wer"] == 0.0
    assert r["missed_words"] == [] and r["extra_words"] == []
    assert r["wpm"] and r["pace"] in {"natural", "measured", "slow", "rushed"}


def test_missing_and_extra_words_are_reported_separately():
    spoken = "The market opens on Friday and people buy fruit before the heat arrives quickly"
    r = score_reading(REFERENCE, spoken, duration_s=20.0)
    assert "early" in r["missed_words"]
    assert "quickly" in r["extra_words"]
    assert 0 < r["accuracy"] < 100


def test_word_order_matters():
    """Bag-of-words scoring would call a shuffled read perfect. It is not."""
    shuffled = " ".join(reversed(REFERENCE.split()))
    assert score_reading(REFERENCE, shuffled, duration_s=20.0)["accuracy"] < 60


def test_racing_through_half_the_text_cannot_inflate_wpm():
    """wpm counts words that actually matched the passage, not words emitted."""
    half = " ".join(REFERENCE.split()[:7])
    fast = score_reading(REFERENCE, half, duration_s=10.0)
    full = score_reading(REFERENCE, REFERENCE, duration_s=10.0)
    assert fast["wpm"] < full["wpm"]


def test_silence_is_reported_not_scored_as_zero_effort():
    r = score_reading(REFERENCE, "", duration_s=8.0)
    assert r["accuracy"] == 0.0
    assert r["wpm"] is None
    assert "microphone" in r["verdict"] or "did not come through" in r["verdict"]


def test_reading_endpoints():
    with TestClient(app) as client:
        uid = "r" + new_id()[:10]
        client.post("/users", json={"user_id": uid, "display_name": "Reader"})

        p = client.get("/reading/passage?level=2").json()
        assert p["level"] == 2 and p["words"] > 10 and p["text"]

        assert client.get("/reading/passage?level=9").status_code == 422

        r = client.post(
            f"/users/{uid}/reading/score",
            json={"reference": p["text"], "spoken": p["text"], "duration_s": 30.0},
        )
        assert r.status_code == 200
        assert r.json()["accuracy"] == 100.0

        missing = client.post(
            "/users/ghost/reading/score",
            json={"reference": "x", "spoken": "x", "duration_s": 1.0},
        )
        assert missing.status_code == 404
