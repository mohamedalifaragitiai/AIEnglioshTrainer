# AI English Coach

A **fully offline, self-hosted** AI English Speaking & Listening Coach that runs on
a single resource-constrained dev workstation (reference host: Intel Core Ultra 9
275HX 24-core, RTX 5080 Laptop 16GB VRAM, 64GB RAM). No cloud APIs. **No Docker.**
Managed entirely with [`uv`](https://docs.astral.sh/uv/).

Two non-negotiable constraints drive every design choice:

1. **Hard 96% resource ceiling.** No single resource (GPU VRAM, GPU compute, RAM,
   CPU, disk) may sustain past 96%. Crossing it triggers **graceful degradation**,
   never a freeze. The `ResourceGuard` enforces this.
2. **Per-user longitudinal profiles.** Every learner owns a durable profile
   tracking skill scores, gaps, and progress across time (Phase 1+).

## Architecture (two paths, one resource broker)

- **Hot path** (synchronous, <300ms to first audio): mic → Silero VAD → Whisper
  `large-v3-turbo` → Qwen3-8B (vLLM) → Kokoro-82M TTS → speaker.
- **Cold path** (asynchronous, deferrable): grammar/vocab/fluency (Qwen3-14B) +
  wav2vec2 GOP pronunciation → versioned scoring → per-user profile → gap
  analysis → plans/reports.
- **Cross-cutting:** `ResourceGuard` (96% ceiling + degradation ladder), Prometheus
  metrics + structured logs, SQLite per-user store, asyncio in-process event bus.

## Requirements

- Python ≥ 3.11 and [`uv`](https://docs.astral.sh/uv/) (do **not** use pip/venv).
- Optional NVIDIA GPU + drivers for VRAM/util sampling. On a CPU-only host the
  guard reports GPU as absent and the system still runs (CPU fallbacks).

## Setup

```bash
uv sync                 # create .venv and install locked deps
cp .env.example .env    # optional: override defaults
```

## Run

```bash
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Then open **http://127.0.0.1:8000/** — the built-in web UI (dashboard + live
practice). Other endpoints:
- UI:      http://127.0.0.1:8000/          (dashboard, radar/trend charts, live mic)
- Health:  http://127.0.0.1:8000/healthz
- Metrics: http://127.0.0.1:8000/metrics   (Prometheus exposition)
- Guard:   http://127.0.0.1:8000/guard     (live degradation level + usage)
- Models:  http://127.0.0.1:8000/models    (status + VRAM budget)
- API docs: http://127.0.0.1:8000/docs

To see the dashboard populated immediately: `uv run python scripts/seed_user.py`
(creates **Abu Ali** with demo history), or click **Load demo data** in the UI.

### Frontend

The UI is a single self-contained page (`frontend/index.html`) served by the app —
**no Node, no build step, no CDN** (inline CSS/JS + hand-drawn canvas charts), in
keeping with the fully-offline rule. It has a **Dashboard** (level/streak/overall/ETA
tiles, an 8-skill radar, an overall-trend line, and a recent-assessments table) and a
**Practice** tab (mic → WebSocket `/ws/session` → streamed transcript/reply/TTS
audio). Live speaking needs models enabled (see *Enabling models*); the dashboard
works from stored/seeded data alone. A polished Next.js + Tailwind version is the
planned Phase 6 upgrade.

## Prove the 96% ceiling (before any model is loaded)

```bash
uv run python scripts/loadtest_guard.py   # synthetic ramp; exits non-zero on failure
uv run pytest                             # unit + API tests
```

The load test ramps **synthetic** resource readings through the guard — it does not
really allocate memory, because actually driving the box to 96% is exactly the
freeze this project prevents. It asserts the guard climbs the degradation ladder,
defers cold-path work, and rejects new sessions at the ceiling while never blocking
the in-flight learner turn.

## Enabling models (Phase 2, opt-in)

No weights ship with the repo and none download automatically. The app boots with
model loading **off** (`COACH_LOAD_MODELS=false`) and reports specs/budget at
`/models`. To actually serve models:

```bash
# 1. See the plan, disk/VRAM budget, and dep status (downloads nothing):
uv run python scripts/setup_models.py

# 2. Install the opt-in ML runtime (kept out of the default env):
uv sync --group models
#    torch + transformers + kokoro are host/CUDA-specific — install per your box
#    (on Windows, use WSL2 + the CUDA wheel index) since vLLM needs Linux anyway.

# 3. Fetch the resident GPU weights (STT + GOP + TTS) into ./models:
uv run python scripts/setup_models.py --download

# 4. Start the LLM server as a SEPARATE process (native Linux/WSL2), OpenAI-API:
#    uv run vllm serve Qwen/Qwen3-8B --gpu-memory-utilization 0.68 --port 8001

# 5. Measure real latency/VRAM, then enable loading (guard verifies the budget):
uv run python scripts/benchmark_models.py
COACH_LOAD_MODELS=true uv run uvicorn backend.main:app --port 8000
```

When `COACH_LOAD_MODELS=true`, startup runs `guard.check_startup_budget` and
**refuses to start** with an actionable message if the resident set (vLLM
reservation + Whisper + GOP + TTS) would cross the 96% VRAM ceiling — rather than
OOM-crashing later. On the 16GB reference GPU the default set fits at ~16.0/16.4GB;
lower `COACH_VLLM_VRAM_FRACTION` or move TTS to CPU if your measured footprints run
higher.

> **Windows note:** vLLM has no native Windows build — run the vLLM server under
> WSL2/Linux (or a remote localhost). The app itself is pure-Python and talks to it
> over HTTP, so the FastAPI app runs fine natively on Windows.

## Build phases

The system is runnable after each phase.

- **Phase 0 — Foundation & guardrails** ✅ *(this commit)*: uv env, settings,
  structured logging, Prometheus `/metrics`, and the `ResourceGuard` (background
  sampler + degradation ladder + hysteresis) with unit tests and the synthetic
  load test. No models loaded yet.
- **Phase 1 — Persistence & per-user profiles** ✅: SQLite (WAL) store, DDD
  aggregates, repositories, forward-only migrations, versioned append-only scoring,
  REST for user CRUD + sessions/assessments + progress queries (trend, streak,
  time-to-next-level), and `scripts/seed_user.py` for Abu Ali.
- **Phase 2 — Model serving through the guard** ✅: `ManagedModel`/`ModelRegistry`
  that refuses to start if the resident set won't fit under the 96% VRAM ceiling;
  OpenAI-compatible vLLM HTTP client (hot 8B / cold 14B, guard-aware); lazy-loaded
  Whisper-turbo / wav2vec2-GOP / Kokoro adapters (opt-in `models` dep group);
  `/models` status + budget API; `setup_models.py` (check-first, logged downloads)
  and `benchmark_models.py`. Weights are **not** bundled — see *Enabling models*.
- **Phase 3 — Hot path** ✅: in-process asyncio event bus; energy VAD + turn
  segmenter (offline, dependency-free; Silero optional); STT/dialogue/TTS stages;
  `HotPathPipeline` (one guard-gated turn, streamed, emits `UtteranceFinalized`);
  `/ws/session` WebSocket loop (PCM16 in → transcript/reply/audio out); and
  `scripts/profile_hotpath.py` proving the <300ms first-audio budget.
- **Phase 4 — Cold-path evaluation & scoring** ✅: event worker consuming
  `UtteranceFinalized` → batched LLM evaluator (grammar/vocab/listening/coherence/
  relevance on the cold 14B, one JSON call) + deterministic fluency/confidence +
  wav2vec2 GOP pronunciation (proxy fallback) → versioned weighted scoring
  (renormalized over present dims) → profile update → `AssessmentReady`. Fully
  **deferrable** under guard pressure and **idempotent**. `/users/{id}/assessments`
  and `/utterances/{id}/evaluator-outputs` expose results.
- **Phase 5 — Gap analysis, plans & reports** ✅: importance-weighted ranked gaps +
  gap snapshots + most-improved; adaptive study planner (difficulty from the recent
  trend, targeted activities per skill); post-session feedback (strengths/weaknesses/
  corrections); and one-click **JSON/CSV/Excel/PDF** report downloads. Endpoints under
  `/users/{id}/gaps|plan|feedback|report`, surfaced in the dashboard UI.
- **Phase 6** — Next.js dashboard.
- **Phase 7** — Hardening: monitoring dashboards, soak tests, CI, docs.

## Golden rules

No Docker · `uv` only (never pip) · no cloud/network at runtime (models load once,
logged) · 96% is a hard ceiling checked before every heavy op · one learner = one
durable profile · hot path never blocks on evaluation · everything observable.

## Repository layout

```
english-coach/
├── config/settings.py            # pydantic-settings; RESOURCE_CEILING=0.96
├── backend/
│   ├── main.py                   # FastAPI app; lifespan boots the guard
│   ├── core/
│   │   ├── resource_guard.py     # the 96% ceiling + degradation ladder
│   │   ├── metrics.py            # prometheus collectors
│   │   └── logging.py            # structlog + correlation ids
│   ├── domain/ hotpath/ coldpath/ persistence/ api/   # (later phases)
├── scripts/loadtest_guard.py     # synthetic ceiling proof (Phase 0 gate)
└── tests/                        # pytest: guard ladder/hysteresis, API
```
