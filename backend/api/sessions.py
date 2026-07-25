"""Sessions, utterances, and assessment recording.

Assessments are the versioned, append-only record. Recording one computes the
weighted overall for the given ``scoring_model_version`` and advances the user's
``current_level`` to match the latest overall — history is never overwritten.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.api.deps import Repositories, get_progress, get_repos
from backend.coldpath.scoring import (
    DIMENSIONS,
    SCORING_MODEL_VERSION,
    compute_overall,
    level_for_overall,
)
from backend.core.util import new_id, now_iso
from backend.domain.models import (
    Assessment,
    Role,
    Session,
    SessionMode,
    Utterance,
)
from backend.persistence.progress import ProgressService

router = APIRouter(tags=["sessions"])


# --- sessions --------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    mode: SessionMode = SessionMode.FREE
    difficulty: float | None = Field(None, ge=0.0, le=1.0)


@router.post(
    "/users/{user_id}/sessions",
    response_model=Session,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    user_id: str,
    body: CreateSessionRequest,
    repos: Repositories = Depends(get_repos),
) -> Session:
    if not repos.users.exists(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id!r} not found")
    return repos.sessions.create(user_id, mode=body.mode, difficulty=body.difficulty)


@router.get("/users/{user_id}/sessions", response_model=list[Session])
def list_sessions(user_id: str, repos: Repositories = Depends(get_repos)) -> list[Session]:
    if not repos.users.exists(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id!r} not found")
    return repos.sessions.list_for_user(user_id)


@router.get("/sessions/{session_id}", response_model=Session)
def get_session(session_id: str, repos: Repositories = Depends(get_repos)) -> Session:
    session = repos.sessions.get(session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"session {session_id!r} not found")
    return session


@router.post("/sessions/{session_id}/end", response_model=Session)
def end_session(
    session_id: str,
    repos: Repositories = Depends(get_repos),
    progress: ProgressService = Depends(get_progress),
) -> Session:
    session = repos.sessions.get(session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"session {session_id!r} not found")
    ended = repos.sessions.end(session_id)
    # Streak is derived from distinct practice days; refresh it on session end.
    progress.recompute_and_store_streak(session.user_id)
    return ended


# --- utterances ------------------------------------------------------------


class AddUtteranceRequest(BaseModel):
    role: Role = Role.LEARNER
    transcript: str | None = None
    audio_path: str | None = None
    stt_confidence: float | None = None
    start_ms: int | None = None
    end_ms: int | None = None


@router.post(
    "/sessions/{session_id}/utterances",
    response_model=Utterance,
    status_code=status.HTTP_201_CREATED,
)
def add_utterance(
    session_id: str, body: AddUtteranceRequest, repos: Repositories = Depends(get_repos)
) -> Utterance:
    session = repos.sessions.get(session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"session {session_id!r} not found")
    return repos.utterances.add(
        session_id,
        session.user_id,
        body.role,
        transcript=body.transcript,
        audio_path=body.audio_path,
        stt_confidence=body.stt_confidence,
        start_ms=body.start_ms,
        end_ms=body.end_ms,
    )


@router.get("/sessions/{session_id}/utterances", response_model=list[Utterance])
def list_utterances(session_id: str, repos: Repositories = Depends(get_repos)) -> list[Utterance]:
    if repos.sessions.get(session_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"session {session_id!r} not found")
    return repos.utterances.list_for_session(session_id)


# --- assessments -----------------------------------------------------------


class RecordAssessmentRequest(BaseModel):
    scores: dict[str, float] = Field(
        ..., description="per-dimension scores 0-100; keys from the 8 dimensions"
    )
    utterance_id: str | None = None
    scoring_model_version: str = SCORING_MODEL_VERSION


@router.post(
    "/sessions/{session_id}/assessments",
    response_model=Assessment,
    status_code=status.HTTP_201_CREATED,
)
def record_assessment(
    session_id: str,
    body: RecordAssessmentRequest,
    repos: Repositories = Depends(get_repos),
) -> Assessment:
    session = repos.sessions.get(session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"session {session_id!r} not found")

    unknown = set(body.scores) - set(DIMENSIONS)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"unknown dimension(s): {sorted(unknown)}; valid: {list(DIMENSIONS)}",
        )
    for dim, val in body.scores.items():
        if not (0.0 <= val <= 100.0):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{dim} score {val} out of range 0-100",
            )

    overall = compute_overall(body.scores, body.scoring_model_version)
    assessment = Assessment(
        assessment_id=new_id("assess"),
        user_id=session.user_id,
        session_id=session_id,
        utterance_id=body.utterance_id,
        scoring_model_version=body.scoring_model_version,
        overall=overall,
        created_at=now_iso(),
        **{d: body.scores.get(d) for d in DIMENSIONS},
    )
    repos.assessments.add(assessment)

    # Advance the user's headline level to match the latest overall.
    repos.users.update(
        session.user_id, current_level=level_for_overall(overall, body.scoring_model_version)
    )
    return assessment
