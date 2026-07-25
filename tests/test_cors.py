"""CORS is enabled for the Next.js dev server origin."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def test_cors_allows_next_dev_origin():
    with TestClient(app) as client:
        r = client.get("/users", headers={"Origin": "http://localhost:3000"})
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_preflight():
    with TestClient(app) as client:
        r = client.options(
            "/users",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert r.status_code in (200, 204)
        assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
