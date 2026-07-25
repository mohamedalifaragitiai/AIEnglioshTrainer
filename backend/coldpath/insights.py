"""Insights service — one entry point for gaps, plans, feedback, and reports.

Wires the analyzers over the repositories and assembles a full ReportData bundle,
renders it to a chosen format, writes the file under the report dir, and records it
in the reports table.
"""

from __future__ import annotations

from pathlib import Path

from backend.coldpath import reporting
from backend.coldpath.feedback import FeedbackBuilder
from backend.coldpath.gap_analysis import GapAnalyzer
from backend.coldpath.planner import Planner
from backend.coldpath.reporting import ReportData
from backend.core import metrics
from backend.core.logging import get_logger
from backend.core.util import new_id
from backend.domain.models import Feedback, GapItem, ImprovementItem, Plan
from backend.persistence.db import Database
from backend.persistence.progress import ProgressService
from backend.persistence.repositories import (
    AssessmentRepository,
    EvaluatorOutputRepository,
    GapSnapshotRepository,
    PlanRepository,
    ReportRepository,
    SessionRepository,
    UserRepository,
)
from config.settings import Settings

log = get_logger("insights")


class InsightsService:
    def __init__(self, db: Database, settings: Settings):
        self.settings = settings
        self.users = UserRepository(db)
        self.sessions = SessionRepository(db)
        self.assessments = AssessmentRepository(db)
        self.evaluator_outputs = EvaluatorOutputRepository(db)
        self.gaps_repo = GapSnapshotRepository(db)
        self.plans_repo = PlanRepository(db)
        self.reports_repo = ReportRepository(db)

        self.progress = ProgressService(self.users, self.sessions, self.assessments)
        self.analyzer = GapAnalyzer(
            self.assessments, self.gaps_repo, target=settings.gap_target_score
        )
        self.planner = Planner(self.analyzer, self.progress, self.users)
        self.feedback_builder = FeedbackBuilder(
            self.assessments, self.evaluator_outputs, self.users, self.progress
        )

    # --- gaps --------------------------------------------------------------

    def gaps(self, user_id: str) -> list[GapItem]:
        return self.analyzer.current_gaps(user_id)

    def snapshot_gaps(self, user_id: str) -> dict[str, float]:
        return self.analyzer.snapshot(user_id)

    def improvement(self, user_id: str, *, days: int = 30) -> list[ImprovementItem]:
        return self.analyzer.improvement(user_id, days=days)

    # --- plan / feedback ---------------------------------------------------

    def plan(self, user_id: str, *, persist: bool = False) -> Plan:
        plan = self.planner.build_plan(user_id)
        if persist:
            self.plans_repo.add(user_id, plan.horizon, plan.model_dump_json())
            metrics.plans_generated_total.inc()
        return plan

    def feedback(self, user_id: str) -> Feedback:
        return self.feedback_builder.build(user_id)

    # --- reports -----------------------------------------------------------

    def report_data(self, user_id: str) -> ReportData | None:
        overview = self.progress.overview(user_id)
        if overview is None:
            return None
        return ReportData(
            overview=overview,
            assessments=self.assessments.list_for_user(user_id, limit=1000),
            gaps=self.analyzer.current_gaps(user_id),
            plan=self.planner.build_plan(user_id),
            feedback=self.feedback_builder.build(user_id),
        )

    def generate_report(self, user_id: str, fmt: str) -> tuple[bytes, str] | None:
        data = self.report_data(user_id)
        if data is None:
            return None
        payload = reporting.render(data, fmt)
        filename = f"{user_id}_{new_id()[:8]}.{fmt}"
        try:
            report_dir = Path(self.settings.resolved_report_dir)
            report_dir.mkdir(parents=True, exist_ok=True)
            path = report_dir / filename
            path.write_bytes(payload)
            self.reports_repo.add(user_id, "all_time", fmt, str(path))
        except Exception as exc:  # noqa: BLE001 — file/record issues shouldn't block download
            log.error("report_persist_failed", error=str(exc))
        metrics.reports_generated_total.labels(fmt).inc()
        return payload, filename
