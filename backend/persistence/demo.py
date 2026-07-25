"""Demo-history seeding shared by the CLI seed script and the /seed-demo endpoint.

Generates a few days of gently improving assessments so the dashboard and progress
queries (trend, streak, time-to-next-level) have realistic data without needing
models or a live session.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.coldpath.scoring import (
    DIMENSIONS,
    SCORING_MODEL_VERSION,
    compute_overall,
    level_for_overall,
)
from backend.core.util import new_id
from backend.domain.models import Assessment, Role, SessionMode
from backend.persistence.progress import ProgressService
from backend.persistence.repositories import (
    AssessmentRepository,
    SessionRepository,
    UserRepository,
    UtteranceRepository,
)

_BASE = {
    "pronunciation": 58,
    "grammar": 60,
    "vocabulary": 55,
    "listening": 62,
    "fluency": 57,
    "confidence": 60,
    "coherence": 63,
    "relevance": 64,
}


def seed_demo_history(
    users: UserRepository,
    sessions: SessionRepository,
    utterances: UtteranceRepository,
    assessments: AssessmentRepository,
    user_id: str,
    *,
    days: int = 6,
) -> int:
    """Create `days` backdated sessions + assessments with an upward trend.

    Returns the number of assessments created. No-op-safe to call once per user
    (callers should check the user has no assessments yet).
    """
    now = datetime.now(UTC)
    for day in range(days):
        when = (now - timedelta(days=days - 1 - day)).isoformat()
        session = sessions.create(user_id, mode=SessionMode.INTERVIEW)
        with sessions.db.connection() as con:
            con.execute(
                "UPDATE sessions SET started_at=?, ended_at=? WHERE session_id=?",
                (when, when, session.session_id),
            )
        utt = utterances.add(
            session.session_id,
            user_id,
            Role.LEARNER,
            transcript=f"Demo answer for day {day + 1}.",
            stt_confidence=0.9,
        )
        scores = {d: min(100.0, _BASE[d] + day * 2.5) for d in DIMENSIONS}
        overall = compute_overall(scores, SCORING_MODEL_VERSION)
        assessments.add(
            Assessment(
                assessment_id=new_id("assess"),
                user_id=user_id,
                session_id=session.session_id,
                utterance_id=utt.utterance_id,
                scoring_model_version=SCORING_MODEL_VERSION,
                overall=overall,
                created_at=when,
                **scores,
            )
        )

    latest = assessments.latest_for_user(user_id)
    if latest and latest.overall is not None:
        users.update(user_id, current_level=level_for_overall(latest.overall))
    ProgressService(users, sessions, assessments).recompute_and_store_streak(user_id)
    return days
