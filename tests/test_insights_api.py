"""API tests for the Phase 5 insights endpoints (via the real app)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.core.util import new_id
from backend.main import app


def _seeded_user(client) -> str:
    uid = "i" + new_id()[:8]
    client.post("/users", json={"user_id": uid, "display_name": "Insights"})
    client.post(f"/dev/users/{uid}/seed-demo")
    return uid


def test_gaps_endpoint_ranked():
    with TestClient(app) as client:
        uid = _seeded_user(client)
        gaps = client.get(f"/users/{uid}/gaps").json()
        assert len(gaps) == 8
        assert gaps[0]["rank"] == 1
        assert gaps[0]["severity"] >= gaps[-1]["severity"]


def test_plan_and_feedback_endpoints():
    with TestClient(app) as client:
        uid = _seeded_user(client)
        plan = client.get(f"/users/{uid}/plan").json()
        assert 0.0 <= plan["difficulty"] <= 1.0
        assert plan["focus_areas"]

        created = client.post(f"/users/{uid}/plan").json()
        assert created["summary"]

        fb = client.get(f"/users/{uid}/feedback").json()
        assert fb["current_level"] >= 1


def test_improvement_and_snapshot():
    with TestClient(app) as client:
        uid = _seeded_user(client)
        imp = client.get(f"/users/{uid}/gaps/improvement?days=30").json()
        assert isinstance(imp, list) and imp
        snap = client.post(f"/users/{uid}/gaps/snapshot").json()
        assert "gaps" in snap


def test_report_downloads_all_formats():
    with TestClient(app) as client:
        uid = _seeded_user(client)
        expected = {
            "json": (b"{", "application/json"),
            # The CSV now opens with a "# ..." attribution line, so the header
            # is the SECOND row. Readers that cannot skip comments need
            # skiprows=1 (pandas: comment="#").
            "csv": (b"# ", "text/csv"),
            "xlsx": (b"PK", "application/vnd.openxmlformats"),
            "pdf": (b"%PDF-", "application/pdf"),
        }
        for fmt, (magic, ctype) in expected.items():
            r = client.get(f"/users/{uid}/report", params={"format": fmt})
            assert r.status_code == 200, (fmt, r.text)
            assert ctype in r.headers["content-type"]
            assert r.content[: len(magic)] == magic
            assert "attachment" in r.headers.get("content-disposition", "")


def test_report_bad_format_422():
    with TestClient(app) as client:
        uid = _seeded_user(client)
        assert client.get(f"/users/{uid}/report", params={"format": "docx"}).status_code == 422


def test_insights_missing_user_404():
    with TestClient(app) as client:
        assert client.get("/users/ghost/gaps").status_code == 404
        assert client.get("/users/ghost/plan").status_code == 404


def test_every_report_format_carries_the_attribution():
    """All four renderers read one constant. This is what stops three of them
    quietly losing the credit the next time a format is touched."""
    import io
    import json as jsonlib
    import zipfile

    from backend.coldpath.reporting import AUTHOR

    with TestClient(app) as client:
        uid = _seeded_user(client)

        body = client.get(f"/users/{uid}/report", params={"format": "json"}).json()
        assert body["report"]["author"] == AUTHOR
        assert AUTHOR in body["report"]["copyright"]

        csv_text = client.get(f"/users/{uid}/report", params={"format": "csv"}).text
        first, second = csv_text.splitlines()[:2]
        assert AUTHOR in first
        # The credit must not displace the header a parser looks for.
        assert second.startswith("created_at")

        pdf = client.get(f"/users/{uid}/report", params={"format": "pdf"}).content
        # PDF content streams are Flate-compressed, so a raw byte search finds
        # nothing even when the text is plainly on the page. Inflate what can be
        # inflated and search that, plus the uncompressed metadata.
        import re as _re
        import zlib

        blobs = [pdf]
        for m in _re.finditer(rb"stream\r?\n(.*?)endstream", pdf, _re.S):
            try:
                blobs.append(zlib.decompress(m.group(1)))
            except zlib.error:
                pass
        assert any(AUTHOR.encode() in b for b in blobs), "no attribution anywhere in the PDF"

        xlsx = client.get(f"/users/{uid}/report", params={"format": "xlsx"}).content
        with zipfile.ZipFile(io.BytesIO(xlsx)) as z:
            # openpyxl may write cell text inline or into a shared-string table
            # depending on the workbook, so scan the parts rather than assume
            # which one exists. core.xml is the metadata that survives copying
            # the cells out of the sheet.
            names = z.namelist()
            parts = {n: z.read(n).decode("utf-8", "replace") for n in names if n.endswith(".xml")}
        assert any(AUTHOR in text for text in parts.values()), "no attribution in the workbook"
        assert AUTHOR in parts["docProps/core.xml"], "author missing from document metadata"

        assert jsonlib.dumps(body["report"])  # serializable, no surprises
