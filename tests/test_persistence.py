"""Tests for the SQLite persistence layer and versioned, append-only storage."""

from __future__ import annotations

import sqlite3

import pytest

from backend.coldpath.scoring import DIMENSIONS, compute_overall
from backend.core.util import new_id, now_iso
from backend.domain.models import Assessment, Role, SessionMode
from backend.persistence.migrations import migrate
from backend.persistence.repositories import is_unique_violation

# --- database / migrations -------------------------------------------------


def test_wal_mode_enabled(db):
    assert db.journal_mode().lower() == "wal"


def test_migrations_are_idempotent(db):
    # `db` fixture already migrated once; a second call applies nothing.
    assert migrate(db) == []


# --- users -----------------------------------------------------------------


def test_user_crud(users):
    u = users.create("abu_ali", "Abu Ali")
    assert u.user_id == "abu_ali"
    assert users.get("abu_ali").display_name == "Abu Ali"
    assert users.exists("abu_ali")

    users.update("abu_ali", display_name="Abu A.", current_level=2)
    got = users.get("abu_ali")
    assert got.display_name == "Abu A."
    assert got.current_level == 2

    assert [u.user_id for u in users.list()] == ["abu_ali"]
    assert users.delete("abu_ali") is True
    assert users.get("abu_ali") is None
    assert users.delete("abu_ali") is False


def test_duplicate_user_is_unique_violation(users):
    users.create("abu_ali", "Abu Ali")
    with pytest.raises(sqlite3.IntegrityError) as exc:
        users.create("abu_ali", "Someone Else")
    assert is_unique_violation(exc.value)


# --- sessions & utterances -------------------------------------------------


def test_session_and_utterance_flow(users, sessions, utterances):
    users.create("abu_ali", "Abu Ali")
    s = sessions.create("abu_ali", mode=SessionMode.INTERVIEW, difficulty=0.4)
    assert s.session_id.startswith("sess_")
    assert sessions.get(s.session_id).mode == SessionMode.INTERVIEW

    assert sessions.get(s.session_id).ended_at is None
    ended = sessions.end(s.session_id)
    assert ended.ended_at is not None

    utterances.add(s.session_id, "abu_ali", Role.LEARNER, transcript="Hello.")
    utterances.add(s.session_id, "abu_ali", Role.COACH, transcript="Hi, how are you?")
    rows = utterances.list_for_session(s.session_id)
    assert len(rows) == 2
    assert {r.role for r in rows} == {Role.LEARNER, Role.COACH}


# --- assessments: versioned & append-only ----------------------------------


def _assessment(user_id, session_id, version, overall_seed):
    scores = {d: float(overall_seed) for d in DIMENSIONS}
    return Assessment(
        assessment_id=new_id("assess"),
        user_id=user_id,
        session_id=session_id,
        scoring_model_version=version,
        overall=compute_overall(scores, version) if version == "v1" else float(overall_seed),
        created_at=now_iso(),
        **scores,
    )


def test_assessments_are_append_only_and_versioned(users, sessions, assessments):
    users.create("abu_ali", "Abu Ali")
    s = sessions.create("abu_ali")

    # Two assessments under v1, one under a hypothetical retuned v2.
    assessments.add(_assessment("abu_ali", s.session_id, "v1", 60))
    assessments.add(_assessment("abu_ali", s.session_id, "v1", 65))
    assessments.add(_assessment("abu_ali", s.session_id, "v2", 70))

    all_rows = assessments.list_for_user("abu_ali")
    assert len(all_rows) == 3  # nothing overwritten

    v1_only = assessments.list_for_user("abu_ali", version="v1")
    assert len(v1_only) == 2
    assert all(a.scoring_model_version == "v1" for a in v1_only)

    v2_only = assessments.list_for_user("abu_ali", version="v2")
    assert len(v2_only) == 1
    assert assessments.count_for_user("abu_ali") == 3


def test_assessment_stores_all_dimensions(users, sessions, assessments):
    users.create("abu_ali", "Abu Ali")
    s = sessions.create("abu_ali")
    a = _assessment("abu_ali", s.session_id, "v1", 72)
    assessments.add(a)
    got = assessments.get(a.assessment_id)
    for d in DIMENSIONS:
        assert getattr(got, d) == pytest.approx(72.0)
    assert got.overall == pytest.approx(72.0)


# --- cascade delete keeps history consistent -------------------------------


def test_delete_user_cascades(users, sessions, utterances, assessments):
    users.create("abu_ali", "Abu Ali")
    s = sessions.create("abu_ali")
    utterances.add(s.session_id, "abu_ali", Role.LEARNER, transcript="x")
    assessments.add(_assessment("abu_ali", s.session_id, "v1", 60))

    users.delete("abu_ali")
    assert sessions.list_for_user("abu_ali") == []
    assert utterances.list_for_session(s.session_id) == []
    assert assessments.count_for_user("abu_ali") == 0


# --- evaluator outputs & gap snapshots -------------------------------------


def test_evaluator_outputs_roundtrip(users, sessions, utterances, evaluator_outputs):
    users.create("abu_ali", "Abu Ali")
    s = sessions.create("abu_ali")
    u = utterances.add(s.session_id, "abu_ali", Role.LEARNER, transcript="x")
    evaluator_outputs.add(u.utterance_id, "grammar", "v1", '{"errors": []}')
    rows = evaluator_outputs.list_for_utterance(u.utterance_id)
    assert len(rows) == 1
    assert rows[0].evaluator == "grammar"


def test_gap_snapshots(users, gaps):
    users.create("abu_ali", "Abu Ali")
    gaps.add("abu_ali", '{"pronunciation": 0.4}')
    gaps.add("abu_ali", '{"pronunciation": 0.2}')
    latest = gaps.latest("abu_ali")
    assert '"pronunciation": 0.2' in latest.gaps_json
    assert gaps.at_or_before("abu_ali", now_iso()) is not None
