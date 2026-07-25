# AI English Coach — Next.js Dashboard (Phase 6)

Production dashboard: **Next.js 14 (App Router) + TypeScript + Tailwind + Recharts**.
Talks to the FastAPI backend over REST + WebSocket. All chart/UI dependencies are
bundled at build time (no runtime CDN), consistent with the project's offline stance.

## Features

- **Dashboard** (`/`): level/streak/overall/ETA tiles, an 8-skill **radar**, an
  **overall-trend** line, **top gaps** bars, an **adaptive study plan**, a recent-
  assessments table, and JSON/CSV/Excel/PDF **report downloads**.
- **Practice** (`/practice`): live mic → 16 kHz PCM over `/ws/session` → streamed
  transcript/reply + TTS playback, with per-turn latency.
- Learner picker + create + "Load demo data", shared across pages.

## Run

The backend must be running first (enables CORS for `localhost:3000`):

```bash
# 1. Backend (repo root)
uv run uvicorn backend.main:app --port 8000

# 2. This app
cd frontend-next
cp .env.local.example .env.local        # set NEXT_PUBLIC_API_BASE if backend isn't on :8000
npm install
npm run dev                             # http://localhost:3000
```

Production: `npm run build && npm run start`. Typecheck: `npm run typecheck`.

## Notes

- Two frontends exist: this **Next.js** app (Phase 6, richer, needs Node) and the
  zero-dependency `frontend/index.html` served directly by FastAPI (built earlier,
  no Node). They talk to the same backend; use whichever fits.
- Live speaking needs models enabled on the backend (`COACH_LOAD_MODELS=true` + a
  vLLM server); the dashboard works from stored/seeded data alone.
