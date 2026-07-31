"""Admin-only cohort views.

Guarded by an explicit admin check rather than by the enforcement middleware.
The middleware only bites when ``COACH_AUTH_REQUIRED`` is on; these endpoints
expose every learner's history, so they must refuse anonymous callers even on an
install that has otherwise left the API open.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.api.deps import Repositories, current_user_id, get_db, get_repos
from backend.persistence.admin_stats import AdminStatsRepository
from backend.persistence.db import Database

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(request: Request, repos: Repositories = Depends(get_repos)) -> str:
    """The calling admin's user_id, or 401/403."""
    uid = current_user_id(request)
    if uid is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    user = repos.users.get(uid)
    if user is None or not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return uid


@router.get("/overview")
def overview(
    active_window_days: int = 7,
    _admin: str = Depends(require_admin),
    db: Database = Depends(get_db),
) -> dict:
    """Every learner, what they have done, and how they are scoring.

    One call rather than a roster fetch followed by a request per learner: the
    dashboard needs all of it at once, and N+1 over a cohort is how a page that
    works with three learners stops working with thirty.
    """
    return AdminStatsRepository(db).overview(active_window_days=active_window_days)
