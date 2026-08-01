"""Insights API — gaps, improvement, plan, feedback, and report downloads."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from backend.coldpath.conversation import ConversationAnalyzer
from backend.coldpath.insights import InsightsService
from backend.coldpath.reporting import REPORT_FORMATS, content_type
from backend.domain.models import Feedback, GapItem, ImprovementItem, Plan

router = APIRouter(prefix="/users/{user_id}", tags=["insights"])


def get_insights(request: Request) -> InsightsService:
    from config.settings import get_settings

    return InsightsService(request.app.state.db, get_settings())


def _require_user(svc: InsightsService, user_id: str) -> None:
    if not svc.users.exists(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id!r} not found")


@router.get("/conversations")
def conversations(user_id: str, request: Request, limit: int = 100) -> list[dict]:
    """Every practice conversation, newest first — one row each."""
    svc = get_insights(request)
    _require_user(svc, user_id)
    return ConversationAnalyzer(request.app.state.db).list_for_user(user_id, limit=limit)


@router.get("/conversations/{session_id}")
def conversation_report(user_id: str, session_id: str, request: Request) -> dict:
    """Full analysis of one conversation: every turn, its corrections, its scores.

    Assembled from stored rows, never a fresh LLM call — opening a report five
    times must not cost five inference runs, and it has to render when the model
    server is down.
    """
    svc = get_insights(request)
    _require_user(svc, user_id)
    report = ConversationAnalyzer(request.app.state.db).analyze(session_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"session {session_id!r} not found")
    # The session id is opaque, so ownership cannot be read off the path.
    if report["user_id"] != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"session {session_id!r} not found")
    return report


@router.get("/activity")
def activity(user_id: str, request: Request, days: int = 365) -> dict:
    """Daily practice counts for a contribution-style heatmap."""
    svc = get_insights(request)
    _require_user(svc, user_id)
    days = max(7, min(days, 730))
    return ConversationAnalyzer(request.app.state.db).activity(user_id, days=days)


@router.get("/history")
def history(user_id: str, request: Request, limit: int = 500) -> list[dict]:
    """Every message exchanged, grouped by conversation, newest first."""
    svc = get_insights(request)
    _require_user(svc, user_id)
    return ConversationAnalyzer(request.app.state.db).history(user_id, limit=limit)


@router.get("/analysis")
def full_analysis(user_id: str, request: Request, limit: int = 200) -> dict:
    """Across every conversation: totals, averages, measured trend, what to fix."""
    svc = get_insights(request)
    _require_user(svc, user_id)
    return ConversationAnalyzer(request.app.state.db).analyze_all(user_id, limit=limit)


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
