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

Then:
- Health:  http://127.0.0.1:8000/healthz
- Metrics: http://127.0.0.1:8000/metrics  (Prometheus exposition)
- Guard:   http://127.0.0.1:8000/guard    (live degradation level + usage)
- API docs: http://127.0.0.1:8000/docs

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
- **Phase 2** — Model serving through the guard (vLLM Qwen3-8B/14B, Whisper turbo,
  wav2vec2 GOP, Kokoro-82M); `setup_models.py`, `benchmark_models.py`.
- **Phase 3** — Hot path over WebSocket (<300ms first audio).
- **Phase 4** — Cold-path evaluators + real GOP pronunciation + versioned scoring.
- **Phase 5** — Gap analysis, adaptive plans, reports (PDF/Excel/CSV/JSON).
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
