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
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.websockets import WebSocket

from backend.api import admin as admin_router
from backend.api import assessments as assessments_router
from backend.api import auth as auth_router
from backend.api import dev as dev_router
from backend.api import insights as insights_router
from backend.api import models as models_router
from backend.api import ops as ops_router
from backend.api import progress as progress_router
from backend.api import sessions as sessions_router
from backend.api import users as users_router
from backend.api.deps import request_token, resolve_token
from backend.coldpath.factory import build_worker
from backend.core.event_bus import EventBus
from backend.core.logging import configure_logging, get_logger
from backend.core.metrics import CONTENT_TYPE, render_metrics
from backend.core.resource_guard import PsutilNvmlSampler, ResourceGuard
from backend.domain.events import AssessmentReady
from backend.hotpath.dialogue import DialogueStage
from backend.hotpath.stt import WhisperSTTStage
from backend.hotpath.tts import KokoroTTSStage
from backend.hotpath.ws_session import HotPathStages, handle_ws_session
from backend.persistence.db import Database
from backend.persistence.migrations import migrate
from backend.persistence.repositories import UserRepository
from backend.serving.adapters import build_default_registry
from backend.serving.base import ModelKind
from config.settings import get_settings
from config.version import VERSION, version_info

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

    # Hot path: event bus + stages (backed by the registry's models). Stages work
    # even when models are disabled — a turn then reports an actionable error.
    bus = EventBus()
    bus.subscribe(AssessmentReady, _on_assessment_ready)
    stt_model = next(m for m in registry.models if m.kind == ModelKind.STT)
    tts_model = next(m for m in registry.models if m.kind == ModelKind.TTS)
    gop_model = next((m for m in registry.models if m.kind == ModelKind.GOP), None)
    stages = HotPathStages(
        stt=WhisperSTTStage(stt_model),  # type: ignore[arg-type]
        dialogue=DialogueStage(
            llm_client,
            system_prompt=settings.hotpath_system_prompt,
            max_tokens=settings.hotpath_reply_max_tokens,
        ),
        tts=KokoroTTSStage(tts_model),  # type: ignore[arg-type]
    )

    # Cold path: worker consumes UtteranceFinalized -> evaluators -> scoring ->
    # profile update -> AssessmentReady. Deferrable under guard pressure.
    worker = build_worker(
        guard=guard, llm_client=llm_client, gop_model=gop_model, db=db, event_bus=bus
    )
    worker.attach(bus)
    await worker.start()

    app.state.guard = guard
    app.state.sampler = sampler
    app.state.db = db
    app.state.model_registry = registry
    app.state.llm_client = llm_client
    app.state.event_bus = bus
    app.state.hotpath_stages = stages
    app.state.coldpath_worker = worker
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
        await worker.stop()
        await bus.drain()
        await registry.unload_all()
        await llm_client.aclose()
        await guard.stop()
        if hasattr(sampler, "shutdown"):
            sampler.shutdown()
        log.info("app_stopped")


async def _on_assessment_ready(ev: AssessmentReady) -> None:
    log.info(
        "assessment_ready_event",
        user_id=ev.user_id,
        session_id=ev.session_id,
        assessment_id=ev.assessment_id,
    )


app = FastAPI(
    title="AI English Coach",
    version=VERSION,
    summary="Fully offline, resource-governed English speaking & listening coach.",
    lifespan=lifespan,
)


@app.get("/healthz", tags=["ops"])
async def healthz() -> dict:
    """Liveness probe."""
    return {"status": "ok", "app": settings.app_name}


@app.get("/version", tags=["ops"])
async def version_endpoint() -> dict:
    """What is actually running here.

    Open like the other ops endpoints: when a deploy looks wrong, the first
    question is which build answered, and needing a session to ask makes that
    harder at exactly the wrong moment.
    """
    return version_info()


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


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths that stay open when COACH_AUTH_REQUIRED is on. "/" is on the list on
# purpose: the served UI *is* the login screen, so gating it would leave nowhere
# to sign in. It ships no data of its own — every figure on it comes from an API
# call that is gated.
#
# /stats and /models sit here with /guard for the same reason: they report the
# machine (VRAM, degradation level, which models are resident), never a learner.
# Gating them broke the restart checks in RESUME.md and would have made an
# unauthenticated Monitor view impossible, for no privacy gained.
_OPEN_PATHS = (
    "/auth",
    "/healthz",
    "/metrics",
    "/guard",
    "/stats",
    "/models",
    "/version",
    "/docs",
    "/redoc",
    "/openapi.json",
)


def _path_owner(path: str) -> str | None:
    """The learner a ``/users/<id>/...`` path belongs to, if any."""
    parts = [p for p in path.split("/") if p]
    return parts[1] if len(parts) >= 2 and parts[0] == "users" else None


@app.middleware("http")
async def enforce_auth(request, call_next):
    """Gate the data API when auth is enforced.

    One middleware rather than a dependency on each router: enforcement has to
    hold for every current and future data route, and the easiest way to get
    that wrong is to add a router and forget the dependency.

    WebSockets do not pass through here (Starlette runs HTTP middleware only);
    ``/ws/session`` checks its own token.
    """
    if not settings.auth_required or request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    if path == "/" or path.startswith("/favicon") or path.startswith(_OPEN_PATHS):
        return await call_next(request)

    user_id = resolve_token(request.app.state.db, request_token(request, settings))
    if user_id is None:
        return JSONResponse({"detail": "authentication required"}, status_code=401)

    # An admin coaches every learner, so the ownership rule does not apply to
    # them — that is the whole difference between the two roles.
    admin = UserRepository(request.app.state.db).is_admin(user_id)

    owner = _path_owner(path)
    if owner is not None and owner != user_id and not admin:
        return JSONResponse({"detail": "not your profile"}, status_code=403)
    if path.rstrip("/") == "/users" and request.method in ("POST", "DELETE") and not admin:
        return JSONResponse(
            {"detail": "accounts are created through /auth/signup"}, status_code=403
        )

    # Hand the resolved identity down so routes don't re-verify the token.
    request.state.user_id = user_id
    request.state.is_admin = admin
    return await call_next(request)


@app.websocket("/ws/session")
async def ws_session_endpoint(websocket: WebSocket) -> None:
    """Live speaking loop: stream PCM16 audio in, get transcript/reply/audio out."""
    await handle_ws_session(websocket, settings)


# Signup/login. Registered first and always open — the gate cannot be behind itself.
app.include_router(auth_router.router)

# Cohort views. Enforces admin itself, so it is safe with auth_required off too.
app.include_router(admin_router.router)

# Per-user profiles, sessions/assessments, and progress queries.
app.include_router(users_router.router)
app.include_router(sessions_router.router)
app.include_router(progress_router.router)
app.include_router(models_router.router)
app.include_router(assessments_router.router)
app.include_router(insights_router.router)
app.include_router(ops_router.router)
app.include_router(dev_router.router)


_FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Serve the built-in single-page UI (dashboard + live practice).

    ``no-cache`` means "revalidate", not "don't store": the ETag still makes the
    common case a 304. Without it the browser applies *heuristic* freshness and
    can serve a stale shell for hours without ever asking — and since the whole
    UI (markup, CSS and script) is this one file, that silently hides every
    frontend fix behind a hard reload the user has no reason to think of doing.
    """
    return FileResponse(_FRONTEND, headers={"Cache-Control": "no-cache"})
