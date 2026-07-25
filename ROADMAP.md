# Roadmap

The phased build (0–7) is complete and the system is runnable/observable after each
phase. This tracks what's done and what's worth doing next.

## Done (Phases 0–7)

- **0 — Foundation & guardrails:** uv env, settings, structured logging, Prometheus
  `/metrics`, and the `ResourceGuard` (96% ceiling, background sampler, degradation
  ladder + hysteresis) with a synthetic load test.
- **1 — Persistence & profiles:** SQLite (WAL), DDD aggregates, repositories,
  migrations, versioned append-only scoring, REST + progress queries, seed script.
- **2 — Model serving:** guard-gated `ModelRegistry` (refuses to start if the min set
  won't fit under 96% VRAM), OpenAI-compatible vLLM client, lazy STT/GOP/TTS adapters,
  `/models`, `setup_models.py` (check-first), `benchmark_models.py`.
- **3 — Hot path:** event bus, energy VAD + segmenter, `HotPathPipeline`, `/ws/session`
  WebSocket loop, `<300ms` first-audio budget proven by `profile_hotpath.py`.
- **4 — Cold path:** worker consuming `UtteranceFinalized`, batched LLM evaluator +
  deterministic fluency/confidence + wav2vec2 GOP, renormalized versioned scoring,
  profile update, `AssessmentReady`. Deferrable + idempotent.
- **5 — Gaps, plans, reports:** ranked gaps, adaptive planner, feedback, and
  JSON/CSV/Excel/PDF reports.
- **6 — Dashboard:** Next.js + TypeScript + Tailwind + Recharts (`frontend-next/`),
  plus a zero-dependency `frontend/index.html` served by FastAPI.
- **7 — Hardening:** soak test under the ceiling, GitHub Actions CI (uv + pytest +
  ruff + soak, and dashboard typecheck/build), Grafana dashboard + Prometheus config,
  docs.

## Next up (candidates)

- **Prove real latency/VRAM on the box:** run `setup_models.py --download`, start
  vLLM (WSL2), then `benchmark_models.py` — replace the estimated per-model VRAM and
  re-validate the 96% budget with measured numbers.
- **Streaming STT partials:** emit interim transcripts during the turn (currently the
  transcript finalizes at end-of-speech).
- **Full forced-alignment GOP:** upgrade the posterior-confidence GOP to phoneme-level
  forced alignment for finer pronunciation scoring.
- **Spaced repetition / vector recall:** optional Chroma/FAISS store for missed vocab
  (kept out of the base system).
- **Auth & multi-learner:** the design targets one learner; add auth if shared.
- **Grafana provisioning:** ship a provisioning bundle so the dashboard auto-loads.
- **Alerting:** Prometheus alert rules for sustained ceiling hits / queue growth.

## Non-goals (by design)

- **Docker** — single-host, latency-critical; run processes via `uv` directly.
- **Cloud/network at runtime** — models load once (logged); everything else is local.
- **Multi-user concurrency tuning** — optimized for one learner at a time.
