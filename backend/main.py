"""FastAPI application.

Boots the ResourceGuard and the SQLite store through the lifespan so the machine is
observable and persistent from startup: ``/metrics`` exposes Prometheus data
(including every guard signal), ``/healthz`` reports liveness, ``/guard`` reports the
live degradation state, and the ``/users`` / ``/sessions`` / progress routers expose
per-user profiles and longitudinal history.

No models are loaded yet. Model loading (Phase 2) will go through
``guard.check_startup_budget`` and refuse to start if the minimum set won't fit.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from backend.api import models as models_router
from backend.api import progress as progress_router
from backend.api import sessions as sessions_router
from backend.api import users as users_router
from backend.core.logging import configure_logging, get_logger
from backend.core.metrics import CONTENT_TYPE, render_metrics
from backend.core.resource_guard import PsutilNvmlSampler, ResourceGuard
from backend.persistence.db import Database
from backend.persistence.migrations import migrate
from backend.serving.adapters import build_default_registry
from config.settings import get_settings

settings = get_settings()
configure_logging(level=settings.log_level, json_logs=settings.log_json)
log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    sampler = PsutilNvmlSampler(disk_path=str(settings.data_dir.anchor or "."))
    guard = ResourceGuard(sampler=sampler, settings=settings)
    await guard.start()

    # Report the startup VRAM budget (informational for now — no models yet).
    fits, budget_msg = guard.check_startup_budget(min_vram_gb=3.5)
    log.info("startup_budget", fits=fits, detail=budget_msg)

    # Persistence: open the SQLite store (WAL) and apply migrations.
    db = Database(settings.resolved_db_path)
    applied = migrate(db)
    log.info(
        "db_ready",
        path=str(settings.resolved_db_path),
        journal_mode=db.journal_mode(),
        migrations_applied=applied,
    )

    # Model serving: build the registry (vLLM hot/cold + STT + GOP + TTS specs).
    # Loading is gated by COACH_LOAD_MODELS. When on, load_all verifies the min
    # resident set fits under the 96% VRAM ceiling and refuses to start otherwise.
    registry, llm_client = build_default_registry(guard, settings)
    if settings.load_models:
        await registry.load_all()  # raises StartupBudgetError if the min set won't fit
    else:
        log.info("models_disabled", detail="COACH_LOAD_MODELS is false; specs registered only")
    log.info("model_budget", **registry.budget())

    app.state.guard = guard
    app.state.sampler = sampler
    app.state.db = db
    app.state.model_registry = registry
    app.state.llm_client = llm_client
    log.info(
        "app_started",
        host=settings.app_host,
        port=settings.app_port,
        ceiling=settings.resource_ceiling,
        models_loaded=settings.load_models,
    )
    try:
        yield
    finally:
        await registry.unload_all()
        await llm_client.aclose()
        await guard.stop()
        if hasattr(sampler, "shutdown"):
            sampler.shutdown()
        log.info("app_stopped")


app = FastAPI(
    title="AI English Coach",
    version="0.1.0",
    summary="Fully offline, resource-governed English speaking & listening coach.",
    lifespan=lifespan,
)


@app.get("/healthz", tags=["ops"])
async def healthz() -> dict:
    """Liveness probe."""
    return {"status": "ok", "app": settings.app_name}


@app.get("/metrics", tags=["ops"])
async def metrics_endpoint() -> Response:
    """Prometheus exposition endpoint."""
    return Response(content=render_metrics(), media_type=CONTENT_TYPE)


@app.get("/guard", tags=["ops"])
async def guard_state() -> dict:
    """Live view of the ResourceGuard: degradation level and smoothed usage."""
    guard: ResourceGuard = app.state.guard
    snap = guard.snapshot()
    return {
        "degradation_level": guard.degradation_level,
        "ceiling": guard.ceiling,
        "soft": guard.soft,
        "usage": {k: (round(v, 4) if v is not None else None) for k, v in snap.ratios.items()},
    }


# Per-user profiles, sessions/assessments, and progress queries.
app.include_router(users_router.router)
app.include_router(sessions_router.router)
app.include_router(progress_router.router)
app.include_router(models_router.router)
