"""Version reporting, and the invariants that keep it honest."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from config.version import VERSION

_ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_and_config_agree():
    """Two files carry the version because packaging reads one and the app the
    other. Nothing but a test stops them drifting."""
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == VERSION


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION), VERSION


def test_changelog_documents_the_current_version():
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"[{VERSION}]" in changelog, f"CHANGELOG.md has no entry for {VERSION}"


def test_version_endpoint_reports_the_build():
    with TestClient(app) as client:
        body = client.get("/version").json()
    assert body["version"] == VERSION
    # git_sha is best-effort: a deployed copy may have no .git and must still
    # answer rather than fail.
    assert "git_sha" in body


def test_version_info_never_raises_outside_a_checkout(monkeypatch):
    import config.version as mod

    monkeypatch.setattr(mod, "_REPO_ROOT", Path("/nonexistent-checkout"))
    mod.git_sha.cache_clear()
    try:
        assert mod.version_info()["version"] == VERSION
    finally:
        mod.git_sha.cache_clear()


def test_openapi_advertises_the_same_version():
    with TestClient(app) as client:
        assert client.get("/openapi.json").json()["info"]["version"] == VERSION


def test_version_stays_readable_without_a_session():
    """When a deploy looks wrong, "which build is this?" must not need a login."""
    from tests.test_auth import auth_enforced

    with TestClient(app) as client, auth_enforced():
        assert client.get("/version").status_code == 200
