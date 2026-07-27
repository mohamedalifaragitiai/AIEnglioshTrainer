"""Insights API — gaps, improvement, plan, feedback, and report downloads."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from backend.api.deps import owned_user_id
from backend.coldpath.insights import InsightsService
from backend.coldpath.reporting import REPORT_FORMATS, content_type
from backend.domain.models import Feedback, GapItem, ImprovementItem, Plan

# Gaps, plans, feedback and reports are all private to one learner.
router = APIRouter(
    prefix="/users/{user_id}",
    tags=["insights"],
    dependencies=[Depends(owned_user_id)],
)


def get_insights(request: Request) -> InsightsService:
    from config.settings import get_settings

    return InsightsService(request.app.state.db, get_settings())


def _require_user(svc: InsightsService, user_id: str) -> None:
    if not svc.users.exists(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id!r} not found")


@router.get("/gaps", response_model=list[GapItem])
def gaps(user_id: str, svc: InsightsService = Depends(get_insights)) -> list[GapItem]:
    _require_user(svc, user_id)
    return svc.gaps(user_id)


@router.post("/gaps/snapshot")
def snapshot_gaps(user_id: str, svc: InsightsService = Depends(get_insights)) -> dict:
    _require_user(svc, user_id)
    return {"user_id": user_id, "gaps": svc.snapshot_gaps(user_id)}


@router.get("/gaps/improvement", response_model=list[ImprovementItem])
def improvement(
    user_id: str,
    days: int = Query(30, ge=1, le=3650),
    svc: InsightsService = Depends(get_insights),
) -> list[ImprovementItem]:
    _require_user(svc, user_id)
    return svc.improvement(user_id, days=days)


@router.get("/plan", response_model=Plan)
def get_plan(user_id: str, svc: InsightsService = Depends(get_insights)) -> Plan:
    _require_user(svc, user_id)
    return svc.plan(user_id)


@router.post("/plan", response_model=Plan)
def create_plan(user_id: str, svc: InsightsService = Depends(get_insights)) -> Plan:
    _require_user(svc, user_id)
    return svc.plan(user_id, persist=True)


@router.get("/feedback", response_model=Feedback)
def feedback(user_id: str, svc: InsightsService = Depends(get_insights)) -> Feedback:
    _require_user(svc, user_id)
    return svc.feedback(user_id)


@router.get("/report")
def report(
    user_id: str,
    format: str = Query("json", description=f"one of {list(REPORT_FORMATS)}"),
    svc: InsightsService = Depends(get_insights),
) -> Response:
    _require_user(svc, user_id)
    if format not in REPORT_FORMATS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"unknown format {format!r}; valid: {list(REPORT_FORMATS)}",
        )
    result = svc.generate_report(user_id, format)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no data for user {user_id!r}")
    payload, filename = result
    return Response(
        content=payload,
        media_type=content_type(format),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
