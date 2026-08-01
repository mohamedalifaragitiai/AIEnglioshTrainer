"""Read-aloud exercise: fetch a passage, submit an attempt, get metrics.

Audio never comes here. The learner reads over the existing ``/ws/session``
socket, which already owns the microphone, the VAD and Whisper; this endpoint
takes the transcript that came back and compares it with the passage. Keeping
the audio path in one place means the reading exercise inherits the guard, the
degradation ladder and the <300ms budget for free.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.api.deps import Repositories, get_repos, require_access
from backend.coldpath.reading import PASSAGES, passage_for, score_reading
from backend.core.logging import get_logger
from backend.persistence.repositories import ReadingRepository

router = APIRouter(tags=["reading"])
log = get_logger("reading")


class ReadingAttempt(BaseModel):
    reference: str = Field(..., min_length=1, description="the passage as shown")
    spoken: str = Field("", description="what STT heard")
    duration_s: float | None = Field(None, ge=0)
    level: int | None = Field(None, ge=0, le=5)
    title: str | None = Field(None, description="passage title, for the history list")


@router.get("/reading/passage")
def reading_passage(level: int = 0, seed: str | None = None) -> dict:
    """A passage at the requested level.

    Carries no learner data, but stays behind the ordinary session check when
    enforcement is on: there is no caller for it except a signed-in learner
    about to read, and a second exemption is a second thing to get wrong.
    """
    if level < 0 or level > max(PASSAGES):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"level must be between 0 and {max(PASSAGES)}",
        )
    return passage_for(level, seed=seed)


@router.post("/users/{user_id}/reading/score")
def score_attempt(
    user_id: str,
    body: ReadingAttempt,
    request: Request,
    repos: Repositories = Depends(get_repos),
) -> dict:
    """Metrics for one read-aloud attempt: accuracy, WER, pace, and what drifted.

    The attempt is stored, so reading accuracy can be trended like any other
    score. Persisting is best-effort: the learner has already read the passage
    and is owed the result, so a storage failure must not swallow it.
    """
    if not repos.users.exists(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id!r} not found")
    require_access(request, user_id)
    result = score_reading(body.reference, body.spoken, duration_s=body.duration_s)
    result["user_id"] = user_id
    result["level"] = body.level
    try:
        result["attempt_id"] = ReadingRepository(request.app.state.db).add(
            user_id, result, level=body.level, title=body.title
        )
    except Exception as exc:  # noqa: BLE001
        log.error("reading_attempt_persist_failed", user_id=user_id, error=str(exc))
        result["attempt_id"] = None
    return result


@router.get("/users/{user_id}/reading/attempts")
def reading_history(
    user_id: str,
    request: Request,
    limit: int = 50,
    repos: Repositories = Depends(get_repos),
) -> dict:
    """Past read-aloud attempts plus the summary that says if they are improving."""
    if not repos.users.exists(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id!r} not found")
    require_access(request, user_id)
    repo = ReadingRepository(request.app.state.db)
    return {
        "user_id": user_id,
        "summary": repo.summary(user_id),
        "attempts": repo.list_for_user(user_id, limit=limit),
    }
