"""Dev/demo conveniences for the built-in UI (local single-learner use)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.deps import Repositories, get_repos, owned_user_id
from backend.domain.models import ProgressOverview
from backend.persistence.demo import seed_demo_history
from backend.persistence.progress import ProgressService

router = APIRouter(prefix="/dev", tags=["dev"])


@router.post(
    "/users/{user_id}/seed-demo",
    response_model=ProgressOverview,
    dependencies=[Depends(owned_user_id)],
)
def seed_demo(user_id: str, repos: Repositories = Depends(get_repos)) -> ProgressOverview:
    """Populate a user with a few days of demo assessments (idempotent-ish: only
    seeds when the user has no assessments yet) so the dashboard has data."""
    if not repos.users.exists(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id!r} not found")
    if repos.assessments.count_for_user(user_id) == 0:
        seed_demo_history(
            repos.users, repos.sessions, repos.utterances, repos.assessments, user_id
        )
    overview = ProgressService(repos.users, repos.sessions, repos.assessments).overview(user_id)
    assert overview is not None
    return overview
