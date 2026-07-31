"""FastAPI dependencies — build repositories/services from app state."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from backend.core.passwords import token_fingerprint
from backend.persistence.db import Database
from backend.persistence.progress import ProgressService
from backend.persistence.repositories import (
    AssessmentRepository,
    AuthSessionRepository,
    CredentialRepository,
    EvaluatorOutputRepository,
    GapSnapshotRepository,
    SessionRepository,
    UserRepository,
    UtteranceRepository,
)
from config.settings import Settings, get_settings


@dataclass
class Repositories:
    users: UserRepository
    sessions: SessionRepository
    utterances: UtteranceRepository
    assessments: AssessmentRepository
    evaluator_outputs: EvaluatorOutputRepository
    gaps: GapSnapshotRepository
    credentials: CredentialRepository
    auth_sessions: AuthSessionRepository

    @classmethod
    def build(cls, db: Database) -> Repositories:
        return cls(
            users=UserRepository(db),
            sessions=SessionRepository(db),
            utterances=UtteranceRepository(db),
            assessments=AssessmentRepository(db),
            evaluator_outputs=EvaluatorOutputRepository(db),
            gaps=GapSnapshotRepository(db),
            credentials=CredentialRepository(db),
            auth_sessions=AuthSessionRepository(db),
        )


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_repos(request: Request) -> Repositories:
    return Repositories.build(request.app.state.db)


def get_progress(request: Request) -> ProgressService:
    repos = Repositories.build(request.app.state.db)
    return ProgressService(repos.users, repos.sessions, repos.assessments)


# --- auth ------------------------------------------------------------------
# Token transport: `Authorization: Bearer <token>` first, then the session
# cookie. The Next.js dashboard runs cross-origin (:3000 -> :8000) where the
# cookie is not sent — CORS here does not allow credentials — so the header is
# the path that works everywhere; the cookie exists for same-origin browsing
# (the served UI and /docs).


def request_token(request: Request, settings: Settings | None = None) -> str | None:
    """The session token presented by this request, if any."""
    settings = settings or get_settings()
    header = request.headers.get("authorization", "")
    if header[:7].lower() == "bearer ":
        return header[7:].strip() or None
    return request.cookies.get(settings.auth_cookie_name) or None


def resolve_token(db: Database, token: str | None) -> str | None:
    """The user a raw token belongs to, or None if absent/unknown/expired."""
    if not token:
        return None
    return AuthSessionRepository(db).resolve(token_fingerprint(token))


def require_access(request: Request, owner_id: str | None) -> None:
    """Refuse unless the caller owns this resource (or is an admin).

    For routes keyed by an opaque id — a session, an utterance — rather than by
    ``/users/{id}/...``. The enforcement middleware can only compare a user id it
    can *see in the path*, so anything addressed by resource id has to check its
    own owner after loading it. That gap let one learner read another's session
    transcripts through /sessions/{id}/utterances.

    No-op when ``auth_required`` is off, matching the rest of the API: that mode
    is a single-learner install with no identities to separate.
    """
    if not get_settings().auth_required:
        return
    uid = current_user_id(request)
    if uid is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
    if owner_id is not None and uid == owner_id:
        return
    if UserRepository(request.app.state.db).is_admin(uid):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "not your profile")


def current_user_id(request: Request) -> str | None:
    """Authenticated user for this request, or None when signed out.

    Never raises: with ``auth_required`` off the whole API stays anonymous, and
    callers that genuinely need an identity say so themselves.
    """
    if getattr(request.state, "user_id", None):
        return str(request.state.user_id)
    return resolve_token(request.app.state.db, request_token(request))
