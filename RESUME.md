# Resume after a reboot

Everything is committed and pushed. The two servers (app + vLLM) stop on shutdown; the
downloaded models, the WSL vLLM venv, and the SQLite data persist. To bring it all
back up on this machine:

## 1. Start vLLM (in WSL2 — holds the LLM on the GPU)

The WSL venv (`~/.vllm-venv`, vLLM 0.11.0 + `transformers<5`) and the AWQ weights are
already installed/cached, so this just loads + serves (no re-download):

```bash
MSYS_NO_PATHCONV=1 wsl bash -lc \
  'bash /mnt/d/AI_English_Coach/english-coach/scripts/run_vllm.sh Qwen/Qwen3-8B-AWQ 8001 0.55'
```
Wait for `Uvicorn running on http://127.0.0.1:8001`. (It runs `--enforce-eager` — apt
can't reach Ubuntu mirrors here to install gcc for `torch.compile`.)

## 2. Start the app (native Windows)

Use the **venv Python directly** — NOT `uv run` (which re-syncs the lockfile and
would strip the host-specific torch/faster-whisper/kokoro installs):

```bash
cd D:/AI_English_Coach/english-coach
./.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```
`.env` already points the app at the vLLM (`Qwen/Qwen3-8B-AWQ`, VRAM fraction 0) and
sets `COACH_LOAD_MODELS=true`, so STT + GOP + TTS load on the GPU at startup.

## 3. Open the UI

- Served UI (no build): **http://127.0.0.1:8000/**
- Next.js dashboard: `cd frontend-next && npm run dev` → **http://localhost:3000**
  (first run after a fresh clone: `npm install`)

## Verify it's live

```bash
curl -s http://127.0.0.1:8000/stats            # VRAM/GPU/CPU + models_loaded 4
curl -s http://127.0.0.1:8000/models/llm/health  # {"healthy": true}
./.venv/Scripts/python.exe scripts/live_turn_check.py   # end-to-end voice turn
```

Expected healthy readings on this box: **4** models loaded — the LLM plus Whisper
(~1.9GB), wav2vec2 GOP (~1.5GB), Kokoro (~0.3GB) — VRAM ~14/17GB (~82%), degradation
level 0. First audio lands in roughly 0.7–3.3s depending on reply length.

> `models_loaded` is **4**, not 5. `.env` points hot and cold at the *same* served
> model (`Qwen/Qwen3-8B-AWQ` does double duty), and the registry now registers one
> entry per distinct model — it used to list it twice and over-report the count.
> The vLLM entry shows `0.0 GB` on purpose: `COACH_VLLM_VRAM_FRACTION=0.0` because
> vLLM is external, so its VRAM is observed by the guard's sampler rather than
> pre-reserved.

## Tests & CI

The whole suite is fast (~15s) and must stay that way:

```bash
./.venv/Scripts/python.exe -m pytest        # 167 tests
./.venv/Scripts/python.exe -m ruff check .
cd frontend-next && npm run typecheck
```

- `pyproject` already sets `addopts = "-q"`. Do **not** add another `-q` — that makes
  it `-qq` and silently hides the `N passed` summary line.
- CI (`.github/workflows/ci.yml`) mirrors this and both jobs are capped with
  `timeout-minutes` (backend 10, frontend 15). The cap exists because a hanging
  WebSocket test once held a runner for 33 minutes and was on track for GitHub's
  6-hour default. Any hang now fails fast instead of sitting "in progress".
- Anything that streams a turn must close it out: every `{"type":"end"}` gets exactly
  one reply, `turn_end` when the turn ran or `turn_skipped` when the take was shorter
  than `vad_min_speech_ms`. The clients keep the mic disabled until they hear back, so
  silence there strands the UI *and* hangs tests. Tests derive the take length from
  `vad_min_speech_ms` rather than hardcoding a frame count.

## Git

```bash
git remote -v    # origin → github.com/mohamedalifaragitiai/AIEnglioshTrainer (personal)
```

- **Personal GitHub only. Never add or push to an Azure DevOps remote** — those are
  work repos.
- Commit identity is set **repo-locally** to the personal address
  (`git config user.email` → `mohamed.ali.farag.iti.ai@gmail.com`). The global config
  is a work address; keep it out of this history.
- The repo is **public**: no weights, `.env`, `data/`, `models/`, or `reports/` are
  tracked (all gitignored). Keep it that way.
- `.gitattributes` enforces LF everywhere. `*.sh` especially — CRLF in `run_vllm.sh`
  breaks it under WSL with a "bad interpreter" error.

## Regenerating the design PNG

`design/solution_design.png` (shown in the README) is rendered from the HTML — after
editing the design, re-render at 2× so the text stays crisp:

```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless --disable-gpu \
  --hide-scrollbars --force-device-scale-factor=2 --window-size=1640,1422 \
  --virtual-time-budget=8000 --user-data-dir="$TEMP/chrome-prof" \
  --screenshot="D:/AI_English_Coach/english-coach/design/solution_design.png" \
  "file:///D:/AI_English_Coach/english-coach/design/solution_design.html"
```

## Machine-specific notes (why the above is the way it is)

- **Driver 577.03 = CUDA 12.9.** Latest vLLM (0.26) ships CUDA-13-only wheels
  (needs driver 580+), so vLLM is pinned to **0.11.0** (torch 2.8+cu129). Its kernels
  match the driver; `transformers` must be `<5` **in the WSL vLLM venv** (5.x broke
  its tokenizer path). The Windows app venv is separate and runs transformers 5.x fine.
- **torch / transformers / kokoro are installed in `.venv` but NOT in
  `pyproject`/`uv.lock`** (host/CUDA-specific). Run app/model scripts with
  `.venv/Scripts/python.exe`, never `uv run`, or they get removed.
- **WSL DNS** works via the default tunneled resolver — don't set a manual
  `/etc/resolv.conf` (that breaks it here).
- Models on disk: STT/GOP/Kokoro in `models/`; Qwen3-8B-AWQ in the WSL HF cache.
- **Isolation:** all in `D:/AI_English_Coach/english-coach` + WSL `~/.vllm-venv`.
  Nothing shared with other projects; app on 8000, vLLM on 8001.
