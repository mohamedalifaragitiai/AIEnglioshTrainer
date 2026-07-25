"""Tests for Phase 5: gap analysis, planner, feedback, and report rendering."""

from __future__ import annotations

import json

import pytest

from backend.coldpath import reporting
from backend.coldpath.insights import InsightsService
from backend.persistence.demo import seed_demo_history
from config.settings import Settings


@pytest.fixture
def seeded(db, users, sessions, utterances, assessments):
    users.create("abu_ali", "Abu Ali")
    seed_demo_history(users, sessions, utterances, assessments, "abu_ali")
    return db


@pytest.fixture
def svc(seeded) -> InsightsService:
    return InsightsService(seeded, Settings())


# --- gap analysis ----------------------------------------------------------


def test_gaps_ranked_by_severity(svc):
    gaps = svc.gaps("abu_ali")
    assert len(gaps) == 8
    severities = [g.severity for g in gaps]
    assert severities == sorted(severities, reverse=True)  # ranked desc
    assert gaps[0].rank == 1
    assert all(g.gap >= 0 for g in gaps)


def test_gaps_empty_without_data(db):
    svc = InsightsService(db, Settings())
    from backend.persistence.repositories import UserRepository

    UserRepository(db).create("newbie", "New Bie")
    assert svc.gaps("newbie") == []


def test_snapshot_persists_gap_vector(svc):
    vector = svc.snapshot_gaps("abu_ali")
    assert set(vector).issubset(
        {"pronunciation", "grammar", "vocabulary", "listening",
         "fluency", "confidence", "coherence", "relevance"}
    )
    assert svc.gaps_repo.latest("abu_ali") is not None


def test_improvement_positive_for_upward_demo(svc):
    # Demo history trends up, so latest > baseline for every dimension.
    imp = svc.improvement("abu_ali", days=30)
    assert imp and all(i.delta >= 0 for i in imp)


# --- planner ---------------------------------------------------------------


def test_plan_has_focus_and_difficulty(svc):
    plan = svc.plan("abu_ali")
    assert 0.0 <= plan.difficulty <= 1.0
    assert 1 <= len(plan.focus_areas) <= 3
    assert plan.focus_areas[0].activities  # actionable items attached
    assert plan.summary


def test_plan_persist_records_row(svc):
    svc.plan("abu_ali", persist=True)
    assert svc.plans_repo.latest("abu_ali") is not None


# --- feedback --------------------------------------------------------------


def test_feedback_strengths_and_level(svc):
    fb = svc.feedback("abu_ali")
    assert fb.current_level >= 1
    assert isinstance(fb.strengths, list)
    assert fb.pronunciation_tip is not None


# --- reporting -------------------------------------------------------------


def test_report_data_assembled(svc):
    data = svc.report_data("abu_ali")
    assert data is not None
    assert len(data.assessments) == 6
    assert len(data.gaps) == 8


def test_render_json(svc):
    data = svc.report_data("abu_ali")
    payload = reporting.render(data, "json")
    parsed = json.loads(payload)
    assert parsed["overview"]["user_id"] == "abu_ali"
    assert len(parsed["assessments"]) == 6


def test_render_csv(svc):
    data = svc.report_data("abu_ali")
    text = reporting.render(data, "csv").decode()
    assert "created_at,overall,pronunciation" in text.splitlines()[0]
    assert len(text.strip().splitlines()) == 7  # header + 6 rows


def test_render_xlsx_is_valid_zip(svc):
    data = svc.report_data("abu_ali")
    payload = reporting.render(data, "xlsx")
    assert payload[:2] == b"PK"  # xlsx is a zip container


def test_render_pdf_has_magic(svc):
    data = svc.report_data("abu_ali")
    payload = reporting.render(data, "pdf")
    assert payload[:5] == b"%PDF-"


def test_generate_report_persists_and_returns(svc):
    payload, filename = svc.generate_report("abu_ali", "json")
    assert payload and filename.endswith(".json")
    assert svc.reports_repo.list_for_user("abu_ali")  # recorded
