"""FastAPI application — Phase 0 skeleton.

Boots the ResourceGuard through the lifespan so the machine is observable from the
first commit: ``/metrics`` exposes Prometheus data (including every guard signal),
``/healthz`` reports liveness, and ``/guard`` reports the live degradation state.

No models are loaded in Phase 0. Model loading (Phase 2) will go through
``guard.check_startup_budget`` and refuse to start if the minimum set won't fit.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from backend.core.logging import configure_logging, get_logger
from backend.core.metrics import CONTENT_TYPE, render_metrics
from backend.core.resource_guard import PsutilNvmlSampler, ResourceGuard
from config.settings import get_settings

settings = get_settings()
configure_logging(level=settings.log_level, json_logs=settings.log_json)
log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    sampler = PsutilNvmlSampler(disk_path=str(settings.data_dir.anchor or "."))
    guard = ResourceGuard(sampler=sampler, settings=settings)
    await guard.start()

    # Report the startup VRAM budget (informational in Phase 0 — no models yet).
    fits, budget_msg = guard.check_startup_budget(min_vram_gb=3.5)
    log.info("startup_budget", fits=fits, detail=budget_msg)

    app.state.guard = guard
    app.state.sampler = sampler
    log.info(
        "app_started",
        host=settings.app_host,
        port=settings.app_port,
        ceiling=settings.resource_ceiling,
    )
    try:
        yield
    finally:
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
