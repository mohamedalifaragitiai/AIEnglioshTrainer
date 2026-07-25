"""Seed a learner profile (default: Abu Ali) with a little demo history.

Idempotent: re-running updates the display name rather than erroring. Creates a few
sessions + versioned assessments spread across recent days so the progress queries
(trend, streak, time-to-next-level) have data to return.

Run:  uv run python scripts/seed_user.py               # seeds abu_ali
      uv run python scripts/seed_user.py --user-id x --name "X"  --no-demo
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from backend.coldpath.scoring import (
    DIMENSIONS,
    SCORING_MODEL_VERSION,
    compute_overall,
    level_for_overall,
)
from backend.core.logging import configure_logging, get_logger
from backend.core.util import new_id
from backend.domain.models import Assessment, Role, SessionMode
from backend.persistence.db import Database
from backend.persistence.migrations import migrate
from backend.persistence.progress import ProgressService
from backend.persistence.repositories import (
    AssessmentRepository,
    SessionRepository,
    UserRepository,
    UtteranceRepository,
)
from config.settings import get_settings

log = get_logger("seed")


def _demo_history(
    repos_users: UserRepository,
    repos_sessions: SessionRepository,
    repos_utts: UtteranceRepository,
    repos_assess: AssessmentRepository,
    user_id: str,
) -> None:
    """Six days of gently improving scores so trends slope upward."""
    base = {
        "pronunciation": 58,
        "grammar": 60,
        "vocabulary": 55,
        "listening": 62,
        "fluency": 57,
        "confidence": 60,
        "coherence": 63,
        "relevance": 64,
    }
    now = datetime.now(UTC)
    for day in range(6):
        # Backdate each session so streak/trend math has real spread.
        when = (now - timedelta(days=5 - day)).isoformat()
        session = repos_sessions.create(user_id, mode=SessionMode.INTERVIEW)
        # Overwrite started_at to the backdated time (seed-only convenience).
        with repos_sessions.db.connection() as con:
            con.execute(
                "UPDATE sessions SET started_at=?, ended_at=? WHERE session_id=?",
                (when, when, session.session_id),
            )
        utt = repos_utts.add(
            session.session_id,
            user_id,
            Role.LEARNER,
            transcript=f"Demo answer for day {day + 1}.",
            stt_confidence=0.9,
        )
        scores = {d: min(100.0, base[d] + day * 2.5) for d in DIMENSIONS}
        overall = compute_overall(scores, SCORING_MODEL_VERSION)
        assessment = Assessment(
            assessment_id=new_id("assess"),
            user_id=user_id,
            session_id=session.session_id,
            utterance_id=utt.utterance_id,
            scoring_model_version=SCORING_MODEL_VERSION,
            overall=overall,
            created_at=when,
            **scores,
        )
        repos_assess.add(assessment)

    # Land current_level on the most recent overall.
    latest = repos_assess.latest_for_user(user_id)
    if latest and latest.overall is not None:
        repos_users.update(user_id, current_level=level_for_overall(latest.overall))


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed a learner profile.")
    parser.add_argument("--user-id", default="abu_ali")
    parser.add_argument("--name", default="Abu Ali")
    parser.add_argument("--no-demo", action="store_true", help="create the user only")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=False)

    db = Database(settings.resolved_db_path)
    migrate(db)

    users = UserRepository(db)
    sessions = SessionRepository(db)
    utts = UtteranceRepository(db)
    assess = AssessmentRepository(db)

    if users.exists(args.user_id):
        users.update(args.user_id, display_name=args.name)
        log.info("user_exists_updated", user_id=args.user_id)
    else:
        users.create(args.user_id, args.name)
        log.info("user_created", user_id=args.user_id, name=args.name)

    if not args.no_demo and assess.count_for_user(args.user_id) == 0:
        _demo_history(users, sessions, utts, assess, args.user_id)
        # Persist the derived streak (the live app does this on session end).
        ProgressService(users, sessions, assess).recompute_and_store_streak(args.user_id)
        log.info("demo_history_seeded", user_id=args.user_id)

    user = users.get(args.user_id)
    n = assess.count_for_user(args.user_id)
    print(
        f"Seeded user {user.user_id!r} ({user.display_name}) — "
        f"level {user.current_level}, streak {user.streak_days}, {n} assessment(s). "
        f"DB: {settings.resolved_db_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
