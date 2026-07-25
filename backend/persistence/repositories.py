"""Repositories — the only place SQL touches the domain.

Each repository takes a :class:`Database` and maps rows to domain models. Writes to
``assessments`` and ``evaluator_outputs`` are append-only by contract (see
``references/data-model.md``): history is never overwritten so trends survive
scoring retunes.
"""

from __future__ import annotations

import sqlite3

from backend.core.util import new_id, now_iso
from backend.domain.models import (
    Assessment,
    EvaluatorOutput,
    GapSnapshot,
    Role,
    Session,
    SessionMode,
    User,
    Utterance,
)
from backend.persistence.db import Database

_ASSESS_COLS = (
    "assessment_id, user_id, session_id, utterance_id, scoring_model_version,"
    " pronunciation, grammar, vocabulary, listening, fluency, confidence,"
    " coherence, relevance, overall, created_at"
)


class UserRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(
        self,
        user_id: str,
        display_name: str,
        *,
        current_level: int = 0,
        settings_json: str | None = None,
    ) -> User:
        user = User(
            user_id=user_id,
            display_name=display_name,
            created_at=now_iso(),
            current_level=current_level,
            streak_days=0,
            settings_json=settings_json,
        )
        with self.db.connection() as con:
            con.execute(
                "INSERT INTO users(user_id, display_name, created_at, current_level,"
                " streak_days, settings_json) VALUES (?,?,?,?,?,?)",
                (
                    user.user_id,
                    user.display_name,
                    user.created_at,
                    user.current_level,
                    user.streak_days,
                    user.settings_json,
                ),
            )
        return user

    def get(self, user_id: str) -> User | None:
        with self.db.connection() as con:
            row = con.execute(
                "SELECT * FROM users WHERE user_id=?", (user_id,)
            ).fetchone()
        return User(**row) if row else None

    def list(self) -> list[User]:
        with self.db.connection() as con:
            rows = con.execute(
                "SELECT * FROM users ORDER BY created_at"
            ).fetchall()
        return [User(**r) for r in rows]

    def update(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        current_level: int | None = None,
        streak_days: int | None = None,
        settings_json: str | None = None,
    ) -> User | None:
        sets, params = [], []
        for col, val in (
            ("display_name", display_name),
            ("current_level", current_level),
            ("streak_days", streak_days),
            ("settings_json", settings_json),
        ):
            if val is not None:
                sets.append(f"{col}=?")
                params.append(val)
        if sets:
            params.append(user_id)
            with self.db.connection() as con:
                con.execute(
                    f"UPDATE users SET {', '.join(sets)} WHERE user_id=?", params
                )
        return self.get(user_id)

    def delete(self, user_id: str) -> bool:
        with self.db.connection() as con:
            cur = con.execute("DELETE FROM users WHERE user_id=?", (user_id,))
            return cur.rowcount > 0

    def exists(self, user_id: str) -> bool:
        with self.db.connection() as con:
            return (
                con.execute(
                    "SELECT 1 FROM users WHERE user_id=?", (user_id,)
                ).fetchone()
                is not None
            )


class SessionRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(
        self, user_id: str, mode: SessionMode = SessionMode.FREE, difficulty: float | None = None
    ) -> Session:
        session = Session(
            session_id=new_id("sess"),
            user_id=user_id,
            mode=mode,
            started_at=now_iso(),
            difficulty=difficulty,
        )
        with self.db.connection() as con:
            con.execute(
                "INSERT INTO sessions(session_id, user_id, mode, started_at,"
                " ended_at, difficulty) VALUES (?,?,?,?,?,?)",
                (
                    session.session_id,
                    session.user_id,
                    str(session.mode),
                    session.started_at,
                    session.ended_at,
                    session.difficulty,
                ),
            )
        return session

    def get(self, session_id: str) -> Session | None:
        with self.db.connection() as con:
            row = con.execute(
                "SELECT * FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
        return Session(**row) if row else None

    def end(self, session_id: str) -> Session | None:
        with self.db.connection() as con:
            con.execute(
                "UPDATE sessions SET ended_at=? WHERE session_id=? AND ended_at IS NULL",
                (now_iso(), session_id),
            )
        return self.get(session_id)

    def list_for_user(self, user_id: str, limit: int = 100) -> list[Session]:
        with self.db.connection() as con:
            rows = con.execute(
                "SELECT * FROM sessions WHERE user_id=? ORDER BY started_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [Session(**r) for r in rows]


class UtteranceRepository:
    def __init__(self, db: Database):
        self.db = db

    def add(
        self,
        session_id: str,
        user_id: str,
        role: Role,
        *,
        transcript: str | None = None,
        audio_path: str | None = None,
        stt_confidence: float | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> Utterance:
        utt = Utterance(
            utterance_id=new_id("utt"),
            session_id=session_id,
            user_id=user_id,
            role=role,
            transcript=transcript,
            audio_path=audio_path,
            stt_confidence=stt_confidence,
            start_ms=start_ms,
            end_ms=end_ms,
            created_at=now_iso(),
        )
        with self.db.connection() as con:
            con.execute(
                "INSERT INTO utterances(utterance_id, session_id, user_id, role,"
                " audio_path, transcript, stt_confidence, start_ms, end_ms, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    utt.utterance_id,
                    utt.session_id,
                    utt.user_id,
                    str(utt.role),
                    utt.audio_path,
                    utt.transcript,
                    utt.stt_confidence,
                    utt.start_ms,
                    utt.end_ms,
                    utt.created_at,
                ),
            )
        return utt

    def list_for_session(self, session_id: str) -> list[Utterance]:
        with self.db.connection() as con:
            rows = con.execute(
                "SELECT * FROM utterances WHERE session_id=? ORDER BY created_at",
                (session_id,),
            ).fetchall()
        return [Utterance(**r) for r in rows]


class AssessmentRepository:
    """Append-only store of versioned, aggregated scores."""

    def __init__(self, db: Database):
        self.db = db

    def add(self, assessment: Assessment) -> Assessment:
        with self.db.connection() as con:
            con.execute(
                f"INSERT INTO assessments({_ASSESS_COLS}) VALUES"
                " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    assessment.assessment_id,
                    assessment.user_id,
                    assessment.session_id,
                    assessment.utterance_id,
                    assessment.scoring_model_version,
                    assessment.pronunciation,
                    assessment.grammar,
                    assessment.vocabulary,
                    assessment.listening,
                    assessment.fluency,
                    assessment.confidence,
                    assessment.coherence,
                    assessment.relevance,
                    assessment.overall,
                    assessment.created_at,
                ),
            )
        return assessment

    def get(self, assessment_id: str) -> Assessment | None:
        with self.db.connection() as con:
            row = con.execute(
                "SELECT * FROM assessments WHERE assessment_id=?", (assessment_id,)
            ).fetchone()
        return Assessment(**row) if row else None

    def list_for_user(
        self,
        user_id: str,
        *,
        since: str | None = None,
        version: str | None = None,
        limit: int = 1000,
    ) -> list[Assessment]:
        sql = "SELECT * FROM assessments WHERE user_id=?"
        params: list = [user_id]
        if since is not None:
            sql += " AND created_at >= ?"
            params.append(since)
        if version is not None:
            sql += " AND scoring_model_version = ?"
            params.append(version)
        sql += " ORDER BY created_at LIMIT ?"
        params.append(limit)
        with self.db.connection() as con:
            rows = con.execute(sql, params).fetchall()
        return [Assessment(**r) for r in rows]

    def latest_for_user(self, user_id: str) -> Assessment | None:
        with self.db.connection() as con:
            row = con.execute(
                "SELECT * FROM assessments WHERE user_id=?"
                " ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return Assessment(**row) if row else None

    def count_for_user(self, user_id: str) -> int:
        with self.db.connection() as con:
            return con.execute(
                "SELECT COUNT(*) FROM assessments WHERE user_id=?", (user_id,)
            ).fetchone()[0]

    def exists_for_utterance(self, utterance_id: str) -> bool:
        """Cold-path idempotency: has this utterance already been scored?"""
        with self.db.connection() as con:
            return (
                con.execute(
                    "SELECT 1 FROM assessments WHERE utterance_id=? LIMIT 1",
                    (utterance_id,),
                ).fetchone()
                is not None
            )


class EvaluatorOutputRepository:
    """Raw evaluator payloads, stored separately for retroactive recompute/audit."""

    def __init__(self, db: Database):
        self.db = db

    def add(
        self, utterance_id: str | None, evaluator: str, version: str, payload_json: str
    ) -> EvaluatorOutput:
        out = EvaluatorOutput(
            id=new_id("eval"),
            utterance_id=utterance_id,
            evaluator=evaluator,
            version=version,
            payload_json=payload_json,
            created_at=now_iso(),
        )
        with self.db.connection() as con:
            con.execute(
                "INSERT INTO evaluator_outputs(id, utterance_id, evaluator, version,"
                " payload_json, created_at) VALUES (?,?,?,?,?,?)",
                (
                    out.id,
                    out.utterance_id,
                    out.evaluator,
                    out.version,
                    out.payload_json,
                    out.created_at,
                ),
            )
        return out

    def list_for_utterance(self, utterance_id: str) -> list[EvaluatorOutput]:
        with self.db.connection() as con:
            rows = con.execute(
                "SELECT * FROM evaluator_outputs WHERE utterance_id=? ORDER BY created_at",
                (utterance_id,),
            ).fetchall()
        return [EvaluatorOutput(**r) for r in rows]


class GapSnapshotRepository:
    def __init__(self, db: Database):
        self.db = db

    def add(self, user_id: str, gaps_json: str) -> GapSnapshot:
        snap = GapSnapshot(
            id=new_id("gap"), user_id=user_id, taken_at=now_iso(), gaps_json=gaps_json
        )
        with self.db.connection() as con:
            con.execute(
                "INSERT INTO gap_snapshots(id, user_id, taken_at, gaps_json)"
                " VALUES (?,?,?,?)",
                (snap.id, snap.user_id, snap.taken_at, snap.gaps_json),
            )
        return snap

    def latest(self, user_id: str) -> GapSnapshot | None:
        with self.db.connection() as con:
            row = con.execute(
                "SELECT * FROM gap_snapshots WHERE user_id=?"
                " ORDER BY taken_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return GapSnapshot(**row) if row else None

    def at_or_before(self, user_id: str, when_iso: str) -> GapSnapshot | None:
        with self.db.connection() as con:
            row = con.execute(
                "SELECT * FROM gap_snapshots WHERE user_id=? AND taken_at <= ?"
                " ORDER BY taken_at DESC LIMIT 1",
                (user_id, when_iso),
            ).fetchone()
        return GapSnapshot(**row) if row else None


def is_unique_violation(exc: Exception) -> bool:
    """True if `exc` is a SQLite UNIQUE/PK constraint failure (e.g. duplicate user)."""
    return isinstance(exc, sqlite3.IntegrityError) and "UNIQUE" in str(exc).upper()
