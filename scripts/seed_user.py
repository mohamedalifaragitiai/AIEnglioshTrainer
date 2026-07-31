"""Seed a learner profile (default: Abu Ali) with a little demo history.

Idempotent: re-running updates the display name rather than erroring, and only
seeds demo history when the user has none. Creates a few backdated sessions +
versioned assessments so the progress queries (trend, streak, time-to-next-level)
have data to return.

Also sets a password and/or the admin flag, so an install can be made ready for
``COACH_AUTH_REQUIRED=true`` without going through the signup form. Re-running
with a new ``--password`` resets it — this is the local recovery path when a
password is forgotten (there is no email to send a reset to).

Run:  uv run python scripts/seed_user.py               # seeds abu_ali
      uv run python scripts/seed_user.py --user-id x --name "X"  --no-demo
      uv run python scripts/seed_user.py --password 'secret' --admin
"""

from __future__ import annotations

import argparse

from backend.core.logging import configure_logging, get_logger
from backend.core.passwords import hash_password
from backend.persistence.db import Database
from backend.persistence.demo import seed_demo_history
from backend.persistence.migrations import migrate
from backend.persistence.repositories import (
    AssessmentRepository,
    CredentialRepository,
    SessionRepository,
    UserRepository,
    UtteranceRepository,
)
from config.settings import get_settings

log = get_logger("seed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed a learner profile.")
    parser.add_argument("--user-id", default="abu_ali")
    parser.add_argument("--name", default="Abu Ali")
    parser.add_argument("--no-demo", action="store_true", help="create the user only")
    parser.add_argument("--password", help="set (or reset) this user's password")
    parser.add_argument(
        "--admin",
        action="store_true",
        help="make this user an admin: sees every learner's profile, not just their own",
    )
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

    if args.password:
        CredentialRepository(db).set(
            args.user_id,
            hash_password(args.password, iterations=settings.auth_hash_iterations),
        )
        log.info("password_set", user_id=args.user_id)

    if args.admin:
        users.set_admin(args.user_id, True)
        log.info("admin_granted", user_id=args.user_id)

    if not args.no_demo and assess.count_for_user(args.user_id) == 0:
        seed_demo_history(users, sessions, utts, assess, args.user_id)
        log.info("demo_history_seeded", user_id=args.user_id)

    user = users.get(args.user_id)
    n = assess.count_for_user(args.user_id)
    print(
        f"Seeded user {user.user_id!r} ({user.display_name}) — "
        f"level {user.current_level}, streak {user.streak_days}, {n} assessment(s)"
        f"{', ADMIN' if user.is_admin else ''}"
        f"{', password set' if args.password else ''}. "
        f"DB: {settings.resolved_db_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
