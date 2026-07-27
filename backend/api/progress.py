"""Progress & profile queries — trends, overview, streak."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.deps import Repositories, get_progress, get_repos, owned_user_id
from backend.coldpath.scoring import DIMENSIONS
from backend.domain.models import ProgressOverview, SkillPoint
from backend.persistence.progress import ProgressService

# Every route here reads one learner's private history: the router itself is gated.
router = APIRouter(
    prefix="/users/{user_id}/progress",
    tags=["progress"],
    dependencies=[Depends(owned_user_id)],
)


@router.get("", response_model=ProgressOverview)
def progress_overview(
    user_id: str, progress: ProgressService = Depends(get_progress)
) -> ProgressOverview:
    overview = progress.overview(user_id)
    if overview is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id!r} not found")
    return overview


@router.get("/trend", response_model=list[SkillPoint])
def skill_trend(
    user_id: str,
    skill: str = Query("overall", description=f"one of {list(DIMENSIONS)} or 'overall'"),
    days: int | None = Query(30, ge=1, le=3650, description="lookback window; omit for all"),
    repos: Repositories = Depends(get_repos),
    progress: ProgressService = Depends(get_progress),
) -> list[SkillPoint]:
    if not repos.users.exists(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id!r} not found")
    try:
        return progress.skill_trend(user_id, skill, days=days)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("/streak/recompute")
def recompute_streak(
    user_id: str,
    repos: Repositories = Depends(get_repos),
    progress: ProgressService = Depends(get_progress),
) -> dict:
    if not repos.users.exists(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id!r} not found")
    return {"user_id": user_id, "streak_days": progress.recompute_and_store_streak(user_id)}
