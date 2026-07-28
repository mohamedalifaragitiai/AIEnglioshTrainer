"""Tests for the served UI and the demo-seed convenience endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.core.util import new_id
from backend.main import app


def test_index_served():
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "AI English" in r.text


def test_index_is_not_cached_by_the_browser():
    """The whole UI is one file. Without an explicit revalidation header the
    browser picks its own heuristic freshness and can serve a stale shell for
    hours, hiding every frontend fix behind a hard reload."""
    with TestClient(app) as client:
        assert client.get("/").headers["cache-control"] == "no-cache"


def test_hidden_utility_beats_component_display_rules():
    """`.hidden` and `.modal-back` are both single-class selectors, so the one
    declared later wins. `.modal-back{display:flex}` comes after `.hidden` and
    silently beat it: the results modal was on screen from page load and Close
    could not dismiss it. `!important` is what keeps the utility authoritative."""
    with TestClient(app) as client:
        css = client.get("/").text
    assert ".hidden{display:none!important}" in css

    # Any later rule that sets its own display on a class also carried by a
    # .hidden-toggled element would re-open the same hole.
    hidden_at = css.index(".hidden{display:none")
    later = css[hidden_at:]
    assert "display:flex" in later, "sanity: .modal-back really is declared later"


def test_seed_demo_populates_dashboard():
    with TestClient(app) as client:
        uid = "d" + new_id()[:8]
        client.post("/users", json={"user_id": uid, "display_name": "Demo"})
        ov = client.post(f"/dev/users/{uid}/seed-demo").json()
        assert ov["assessments_count"] == 6
        assert ov["current_level"] >= 1
        assert ov["streak_days"] == 6
        # Trend now has points to chart.
        trend = client.get(f"/users/{uid}/progress/trend?skill=overall&days=3650").json()
        assert len(trend) == 6


def test_seed_demo_missing_user_404():
    with TestClient(app) as client:
        assert client.post("/dev/users/ghost/seed-demo").status_code == 404
