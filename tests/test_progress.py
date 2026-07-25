"""Tests for longitudinal progress queries: trend, streak, time-to-next-level."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.coldpath.scoring import DIMENSIONS, compute_overall
from backend.core.util import new_id
from backend.domain.models import Assessment


def _iso_days_ago(n: int) -> str:
    return (datetime.now(UTC) - timedelta(days=n)).isoformat()


def _add_assessment(assessments, user_id, overall_seed, created_at, version="v1"):
    scores = {d: float(overall_seed) for d in DIMENSIONS}
    assessments.add(
        Assessment(
            assessment_id=new_id("assess"),
            user_id=user_id,
            scoring_model_version=version,
            overall=compute_overall(scores, version),
            created_at=created_at,
            **scores,
        )
    )


def _backdated_session(sessions, user_id, days_ago: int):
    s = sessions.create(user_id)
    when = _iso_days_ago(days_ago)
    with sessions.db.connection() as con:
        con.execute(
            "UPDATE sessions SET started_at=? WHERE session_id=?", (when, s.session_id)
        )
    return s


# --- skill trend -----------------------------------------------------------


def test_skill_trend_filters_by_window(users, assessments, progress):
    users.create("abu_ali", "Abu Ali")
    _add_assessment(assessments, "abu_ali", 50, _iso_days_ago(40))  # outside 30d
    _add_assessment(assessments, "abu_ali", 60, _iso_days_ago(10))  # inside
    _add_assessment(assessments, "abu_ali", 70, _iso_days_ago(1))   # inside

    within = progress.skill_trend("abu_ali", "fluency", days=30)
    assert len(within) == 2
    assert [p.value for p in within] == [60.0, 70.0]

    all_time = progress.skill_trend("abu_ali", "fluency", days=None)
    assert len(all_time) == 3


def test_skill_trend_overall_and_unknown(users, assessments, progress):
    users.create("abu_ali", "Abu Ali")
    _add_assessment(assessments, "abu_ali", 60, _iso_days_ago(1))
    assert progress.skill_trend("abu_ali", "overall", days=None)[0].value == 60.0
    try:
        progress.skill_trend("abu_ali", "not_a_skill")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


# --- streak ----------------------------------------------------------------


def test_streak_counts_consecutive_days(users, sessions, progress):
    users.create("abu_ali", "Abu Ali")
    for d in (0, 1, 2):  # today, yesterday, day before → streak 3
        _backdated_session(sessions, "abu_ali", d)
    assert progress.streak_days("abu_ali") == 3


def test_streak_breaks_on_gap(users, sessions, progress):
    users.create("abu_ali", "Abu Ali")
    _backdated_session(sessions, "abu_ali", 0)  # today
    _backdated_session(sessions, "abu_ali", 1)  # yesterday
    _backdated_session(sessions, "abu_ali", 5)  # gap → not part of the run
    assert progress.streak_days("abu_ali") == 2


def test_streak_zero_without_sessions(users, progress):
    users.create("abu_ali", "Abu Ali")
    assert progress.streak_days("abu_ali") == 0


def test_recompute_and_store_streak_persists(users, sessions, progress):
    users.create("abu_ali", "Abu Ali")
    _backdated_session(sessions, "abu_ali", 0)
    _backdated_session(sessions, "abu_ali", 1)
    assert progress.recompute_and_store_streak("abu_ali") == 2
    assert users.get("abu_ali").streak_days == 2


# --- time to next level ----------------------------------------------------


def test_time_to_next_level_insufficient_data(users, assessments, progress):
    users.create("abu_ali", "Abu Ali")
    _add_assessment(assessments, "abu_ali", 60, _iso_days_ago(1))
    level, eta = progress.time_to_next_level("abu_ali")
    assert (level, eta) == (None, None)


def test_time_to_next_level_positive_slope(users, assessments, progress):
    users.create("abu_ali", "Abu Ali")
    # Rising overall over 5 days: 60 → 64 → 68 (level 2 threshold at ≤69).
    _add_assessment(assessments, "abu_ali", 60, _iso_days_ago(4))
    _add_assessment(assessments, "abu_ali", 64, _iso_days_ago(2))
    _add_assessment(assessments, "abu_ali", 68, _iso_days_ago(0))
    level, eta = progress.time_to_next_level("abu_ali")
    assert level == 3  # 68 → current level 2, next is 3
    assert eta is not None and eta > 0


def test_time_to_next_level_flat_slope(users, assessments, progress):
    users.create("abu_ali", "Abu Ali")
    for d in (4, 2, 0):
        _add_assessment(assessments, "abu_ali", 60, _iso_days_ago(d))  # flat
    level, eta = progress.time_to_next_level("abu_ali")
    assert level == 3  # 60 → current level 2, so the next target level is 3
    assert eta is None  # flat trend ⇒ no positive ETA


# --- overview --------------------------------------------------------------


def test_overview_assembles_headline(users, sessions, assessments, progress):
    users.create("abu_ali", "Abu Ali")
    _backdated_session(sessions, "abu_ali", 0)
    _add_assessment(assessments, "abu_ali", 72, _iso_days_ago(0))
    ov = progress.overview("abu_ali")
    assert ov.user_id == "abu_ali"
    assert ov.assessments_count == 1
    assert ov.latest_overall == 72.0
    assert set(ov.latest_scores) == set(DIMENSIONS)


def test_overview_missing_user(progress):
    assert progress.overview("ghost") is None
