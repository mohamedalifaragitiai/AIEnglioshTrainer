"""Schema migrations.

Forward-only, tracked in ``schema_migrations``. Each migration is (version, SQL);
``migrate`` applies any not yet recorded, inside a transaction. The full Phase 1
schema is migration 001 and mirrors ``references/data-model.md``.
"""

from __future__ import annotations

from backend.core.logging import get_logger
from backend.core.util import now_iso
from backend.persistence.db import Database

log = get_logger("migrations")

_SCHEMA_001 = """
CREATE TABLE IF NOT EXISTS users (
  user_id        TEXT PRIMARY KEY,
  display_name   TEXT NOT NULL,
  created_at     TEXT NOT NULL,
  current_level  INTEGER NOT NULL DEFAULT 0,
  streak_days    INTEGER NOT NULL DEFAULT 0,
  settings_json  TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
  session_id   TEXT PRIMARY KEY,
  user_id      TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  mode         TEXT NOT NULL,
  started_at   TEXT NOT NULL,
  ended_at     TEXT,
  difficulty   REAL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_time ON sessions(user_id, started_at);

CREATE TABLE IF NOT EXISTS utterances (
  utterance_id TEXT PRIMARY KEY,
  session_id   TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  user_id      TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  role         TEXT NOT NULL,
  audio_path   TEXT,
  transcript   TEXT,
  stt_confidence REAL,
  start_ms     INTEGER,
  end_ms       INTEGER,
  created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_utt_session ON utterances(session_id);

CREATE TABLE IF NOT EXISTS assessments (
  assessment_id         TEXT PRIMARY KEY,
  user_id               TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  session_id            TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
  utterance_id          TEXT REFERENCES utterances(utterance_id) ON DELETE SET NULL,
  scoring_model_version TEXT NOT NULL,
  pronunciation REAL, grammar REAL, vocabulary REAL, listening REAL,
  fluency REAL, confidence REAL, coherence REAL, relevance REAL,
  overall REAL,
  created_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assess_user_time ON assessments(user_id, created_at);

CREATE TABLE IF NOT EXISTS evaluator_outputs (
  id            TEXT PRIMARY KEY,
  utterance_id  TEXT REFERENCES utterances(utterance_id) ON DELETE CASCADE,
  evaluator     TEXT NOT NULL,
  version       TEXT NOT NULL,
  payload_json  TEXT NOT NULL,
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_utt ON evaluator_outputs(utterance_id);

CREATE TABLE IF NOT EXISTS gap_snapshots (
  id          TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  taken_at    TEXT NOT NULL,
  gaps_json   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gap_user_time ON gap_snapshots(user_id, taken_at);

CREATE TABLE IF NOT EXISTS plans (
  plan_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, horizon TEXT, plan_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
  report_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  period TEXT NOT NULL, created_at TEXT NOT NULL, format TEXT, path TEXT
);

CREATE TABLE IF NOT EXISTS achievements (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  code TEXT NOT NULL, earned_at TEXT NOT NULL
);
"""

# Auth. Credentials live in their own table rather than as columns on `users`:
# a learner profile is meaningful without a password (the seeded demo user, and
# every profile created before auth existed), and keeping the hash out of the
# `users` row means `SELECT * FROM users` — which the User model maps directly —
# can never accidentally serialize it into an API response.
#
# `auth_sessions` is login sessions; the Phase 1 `sessions` table is *practice*
# sessions. Different things, hence the prefix.
_SCHEMA_002 = """
CREATE TABLE IF NOT EXISTS user_credentials (
  user_id       TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
  algo          TEXT NOT NULL,
  iterations    INTEGER NOT NULL,
  salt          TEXT NOT NULL,
  digest        TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
  token_hash    TEXT PRIMARY KEY,
  user_id       TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  created_at    TEXT NOT NULL,
  expires_at    TEXT NOT NULL,
  last_seen_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry ON auth_sessions(expires_at);
"""

# (version, description, sql) — append new tuples; never rewrite an applied one.
MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "initial schema", _SCHEMA_001),
    (2, "auth: credentials + login sessions", _SCHEMA_002),
]


def migrate(db: Database) -> list[int]:
    """Apply pending migrations. Returns the versions applied this call."""
    applied: list[int] = []
    with db.connection() as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY, description TEXT, applied_at TEXT NOT NULL)"
        )
        done = {row[0] for row in con.execute("SELECT version FROM schema_migrations")}
        for version, description, sql in MIGRATIONS:
            if version in done:
                continue
            con.executescript(sql)
            con.execute(
                "INSERT INTO schema_migrations(version, description, applied_at)"
                " VALUES (?, ?, ?)",
                (version, description, now_iso()),
            )
            applied.append(version)
            log.info("migration_applied", version=version, description=description)
    return applied
