"""Report generation — JSON, CSV, Excel (xlsx), PDF.

Assembles a learner's headline profile, per-dimension assessment history, ranked
gaps, adaptive plan, and feedback into one report, then renders it to the requested
format (bytes). Offline/pure-Python: openpyxl for xlsx, reportlab for PDF. Rendered
files are also written under the report dir and recorded in the reports table.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass

from backend.coldpath.scoring import DIMENSIONS
from backend.domain.models import (
    Assessment,
    Feedback,
    GapItem,
    Plan,
    ProgressOverview,
)

REPORT_FORMATS = ("json", "csv", "xlsx", "pdf")

_CONTENT_TYPES = {
    "json": "application/json",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


def content_type(fmt: str) -> str:
    return _CONTENT_TYPES[fmt]


@dataclass
class ReportData:
    overview: ProgressOverview
    assessments: list[Assessment]
    gaps: list[GapItem]
    plan: Plan
    feedback: Feedback


def _payload(data: ReportData) -> dict:
    return {
        "overview": data.overview.model_dump(),
        "gaps": [g.model_dump() for g in data.gaps],
        "plan": data.plan.model_dump(),
        "feedback": data.feedback.model_dump(),
        "assessments": [a.model_dump() for a in data.assessments],
    }


def render_json(data: ReportData) -> bytes:
    return json.dumps(_payload(data), indent=2).encode("utf-8")


def render_csv(data: ReportData) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["created_at", "overall", *DIMENSIONS, "scoring_model_version"])
    for a in data.assessments:
        writer.writerow(
            [a.created_at, a.overall, *[getattr(a, d) for d in DIMENSIONS], a.scoring_model_version]
        )
    return buf.getvalue().encode("utf-8")


def render_xlsx(data: ReportData) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ov = data.overview

    ws = wb.active
    ws.title = "Summary"
    ws.append(["Learner", ov.display_name, f"({ov.user_id})"])
    ws.append(["Level", ov.current_level, f"next: {ov.next_level}"])
    ws.append(["Streak (days)", ov.streak_days])
    ws.append(["Latest overall", ov.latest_overall])
    ws.append(["Est. days to next level", ov.estimated_days_to_next_level])
    ws.append([])
    ws.append(["Plan"])
    ws.append([data.plan.summary])
    for fa in data.plan.focus_areas:
        ws.append([fa.skill, fa.score, fa.why])

    wa = wb.create_sheet("Assessments")
    wa.append(["created_at", "overall", *DIMENSIONS])
    for a in data.assessments:
        wa.append([a.created_at, a.overall, *[getattr(a, d) for d in DIMENSIONS]])

    wg = wb.create_sheet("Gaps")
    wg.append(["rank", "skill", "score", "target", "gap", "severity"])
    for g in data.gaps:
        wg.append([g.rank, g.skill, g.score, g.target, g.gap, g.severity])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def render_pdf(data: ReportData) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas

    ov = data.overview
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y = height - 2 * cm

    def line(text: str, size: int = 11, dy: float = 0.6 * cm, bold: bool = False) -> None:
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(2 * cm, y, text[:110])
        y -= dy

    line("AI English Coach — Progress Report", 16, 1.0 * cm, bold=True)
    line(f"Learner: {ov.display_name} ({ov.user_id})", 12, bold=True)
    line(f"Level {ov.current_level}  |  Streak {ov.streak_days}d  |  "
         f"Overall {round(ov.latest_overall) if ov.latest_overall else '-'}  |  "
         f"ETA to next level: {ov.estimated_days_to_next_level or '-'} days")
    y -= 0.3 * cm
    line("Ranked gaps", 13, bold=True)
    for g in data.gaps[:8]:
        line(f"  {g.rank}. {g.skill}: {g.score:.0f}/{g.target:.0f}  "
             f"(gap {g.gap:.0f}, severity {g.severity:.2f})")
    y -= 0.2 * cm
    line("Study plan", 13, bold=True)
    line(f"  {data.plan.summary}")
    for fa in data.plan.focus_areas:
        activity = fa.activities[0] if fa.activities else ""
        line(f"  - {fa.skill} ({fa.score:.0f}): {activity}", 10, 0.5 * cm)
    y -= 0.2 * cm
    line("Feedback", 13, bold=True)
    line(f"  Strengths: {', '.join(data.feedback.strengths) or '-'}", 10, 0.5 * cm)
    line(f"  To improve: {', '.join(data.feedback.weaknesses) or '-'}", 10, 0.5 * cm)
    if data.feedback.pronunciation_tip:
        line(f"  Tip: {data.feedback.pronunciation_tip}", 10, 0.5 * cm)

    c.showPage()
    c.save()
    return buf.getvalue()


def render(data: ReportData, fmt: str) -> bytes:
    if fmt == "json":
        return render_json(data)
    if fmt == "csv":
        return render_csv(data)
    if fmt == "xlsx":
        return render_xlsx(data)
    if fmt == "pdf":
        return render_pdf(data)
    raise ValueError(f"unknown report format: {fmt!r}")
