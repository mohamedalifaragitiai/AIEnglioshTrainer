"""FastAPI dependencies — build repositories/services from app state.

Also home to the auth dependencies. ``current_user`` resolves the bearer token;
``owned_user_id`` is the one every user-scoped route must use, because a learner's
history is private to them.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.auth.service import AuthService
from backend.domain.models import User
from backend.persistence.db import Database
from backend.persistence.progress import ProgressService
from backend.persistence.repositories import (
    AssessmentRepository,
    AuthTokenRepository,
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
    tokens: AuthTokenRepository

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
            tokens=AuthTokenRepository(db),
        )


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_repos(request: Request) -> Repositories:
    return Repositories.build(request.app.state.db)


def get_progress(request: Request) -> ProgressService:
    repos = Repositories.build(request.app.state.db)
    return ProgressService(repos.users, repos.sessions, repos.assessments)


def get_settings_dep() -> Settings:
    return get_settings()


def get_auth(request: Request) -> AuthService:
    repos = Repositories.build(request.app.state.db)
    return AuthService(repos.users, repos.credentials, repos.tokens, get_settings())


# auto_error=False so a missing header yields our own 401 with a useful message
# instead of FastAPI's bare "Not authenticated".
_bearer = HTTPBearer(auto_error=False, description="Token from POST /auth/login")


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    auth: AuthService = Depends(get_auth),
) -> User:
    """The authenticated learner, or 401. Use for anything that reads private data."""
    if creds is None or not creds.credentials:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing bearer token — log in at POST /auth/login",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = auth.resolve(creds.credentials)
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "token is invalid, expired or revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def owned_user_id(user_id: str, user: User = Depends(current_user)) -> str:
    """Validate that the path's ``user_id`` is the caller's own.

    404 rather than 403 on a mismatch: confirming that another learner exists is
    itself a leak.
    """
    if user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id!r} not found")
    return user_id


def owned_session_id(
    session_id: str,
    user: User = Depends(current_user),
    repos: Repositories = Depends(get_repos),
) -> str:
    """Validate that a session belongs to the caller (session ids are guessable-ish,
    and a session exposes transcripts)."""
    session = repos.sessions.get(session_id)
    if session is None or session.user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"session {session_id!r} not found")
    return session_id
