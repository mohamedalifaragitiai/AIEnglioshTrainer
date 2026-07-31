# Resume after a reboot

Everything is committed and pushed. The two servers (app + vLLM) stop on shutdown; the
downloaded models, the WSL vLLM venv, and the SQLite data persist. To bring it all
back up on this machine:

> **Two machines run this project.** Everything up to "Machine-specific notes" describes
> the **D: box** (17GB GPU, WSL2 + vLLM). For the **M: box** (6.44GB RTX 4050, no WSL,
> everything on M:), skip to [Profile B](#profile-b--m-drive-644gb-gpu-no-wsl) — its
> start commands and model set are different.

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

## Accounts

Signup/login exist (`/auth/*`, plus a screen in both UIs) but enforcement is
**off** unless `COACH_AUTH_REQUIRED=true` is in `.env` — with it off nothing
changes and every client stays anonymous, which is why the start scripts above
need no token. If you turn it on, create the account *first* (the seeded
`abu_ali` has no password; signing up with that id claims the profile and keeps
its history), or the UI will hold you at a sign-in screen you cannot pass.
`live_turn_check.py` connects anonymously and will fail with close code 4401
until it is given a token. The verification curls above keep working either way:
`/healthz`, `/metrics`, `/guard`, `/stats` and `/models` report the machine, not
a learner, so they stay open. See the README's *Accounts* section.

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

---

# Profile B — M: drive, 6.44GB GPU, no WSL

A second machine runs the same code with a different runtime. Nothing here lives on
C:: the interpreter, venv, every package/model cache, the weights, and temp all sit
under `M:\AIEnglioshTrainer`. Node is the pre-existing system install on C: (v24.14.0),
but its cache is redirected to M: via an untracked `frontend-next\.npmrc`.

```
M:\AIEnglioshTrainer\
  AIEnglioshTrainer\      the git repo (+ .venv, data\, models\)
  tools\uv\               uv 0.11.32 (standalone binary)
  tools\python\           CPython 3.12.13 (installed by uv, NOT on C:)
  tools\llamacpp\         llama.cpp b10154, CUDA 12.4 build + CUDA runtime
  models-llm\             Qwen3-4B-Instruct-2507-Q4_K_M.gguf
  cache\{uv,pip,hf,npm,torch}\  tmp\
  env.ps1 start-llm.ps1 start-app.ps1
```

`env.ps1` is the whole trick: it exports `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR`,
`PIP_CACHE_DIR`, `HF_HOME`, `HF_HUB_CACHE`, `HF_DATASETS_CACHE`, `TRANSFORMERS_CACHE`,
`TORCH_HOME`, `npm_config_cache`, and `TMP`/`TEMP` onto M:. Dot-source it before
running anything by hand.

## Start it (two terminals, in this order)

The app health-checks the LLM at startup and refuses to boot if 8001 is silent.

```powershell
M:\AIEnglioshTrainer\start-llm.ps1     # wait for "listening on ... 8001"
M:\AIEnglioshTrainer\start-app.ps1     # wait for "Uvicorn running on ... 8000"
```

Same UIs as Profile A: served UI on <http://127.0.0.1:8000/>, Next.js dashboard via
`cd frontend-next; npm run dev` on <http://localhost:3000>.

A fresh clone starts with an empty DB, so seed the learner once — otherwise the
WebSocket closes with code **4404** (unknown user) and `live_turn_check.py` dies
mid-stream:

```powershell
. M:\AIEnglioshTrainer\env.ps1
& $env:COACH_PY scripts\seed_user.py
```

## What differs from Profile A, and why

| | Profile A (D:) | Profile B (M:) |
|---|---|---|
| VRAM | ~17GB | **6.44GB** (RTX 4050 Laptop) |
| Driver | 577.03 / CUDA 12.9 | **581.95 / CUDA 13.0** |
| LLM server | vLLM in WSL2 | **llama.cpp on native Windows** — no WSL distro |
| LLM | Qwen3-8B-AWQ (~5.5GB) | **Qwen3-4B-Instruct-2507 Q4_K_M** (~2.4GB) |
| STT precision | float16 (~1.9GB) | **int8_float16** (~1.1GB) |
| GOP device | cuda (~1.5GB) | **cpu** (cold path only) |

The 6.44GB budget drives every swap: Profile A's resident set is ~14GB and does not
fit. The app never imports vLLM — it only speaks OpenAI-compatible HTTP to `/v1/*` —
so `llama-server` is a drop-in, with `--alias` set to match `COACH_VLLM_HOT_MODEL`.

Qwen3-4B-**Instruct**-2507 is deliberate: the hybrid-thinking Qwen3 models emit
`<think>` blocks into a latency-sensitive voice reply.

`llama-server` runs `-c 4096` with `--cache-type-k q8_0 --cache-type-v q8_0`. With an
f16 KV cache at `-c 8192` the resident set measured **5.7GB = 88.5%**, a hair over the
guard's `ladder_l1` (0.88), which parks *all* cold-path assessment work and made
`test_ws_turn_flows_to_cold_path_assessment` fail. Quantizing the KV cache drops it
clear of that edge.

As in Profile A, `COACH_VLLM_VRAM_FRACTION=0.0` because the LLM server is external —
its VRAM is observed by the sampler, not pre-reserved. Hot and cold point at the same
served model, so `models_loaded` is **4**.

## Healthy readings on the M: box

- `models_loaded` **4**, all `loaded`; `degradation_level` **0**
- VRAM **3.8–4.3GB of 6.44GB** (~60–67%), under the 0.88 soft threshold
- `live_turn_check.py` **PASS** — STT ~0.8–1.0s, LLM ~0.15–0.19s, first audio
  **~1.2–1.5s**; generation ~67 tok/s
- `pytest` **167 passed**, `ruff` clean, `npm run typecheck` clean

## Profile B gotchas

- Run with `.venv\Scripts\python.exe`, **never `uv run`** — same reason as Profile A.
- `env.ps1` prepends `torch\lib` to PATH. CTranslate2 (faster-whisper) loads
  cuBLAS/cuDNN at runtime and the torch wheel holds the only copy on this box;
  without it STT fails to init on CUDA.
- Kokoro's G2P (misaki) needs spaCy's `en_core_web_sm` and tries to `pip install` it
  at model-load time — which fails, because a uv-created venv has no `pip`, and TTS
  then aborts app startup. After any venv rebuild:
  `& $env:COACH_UV pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl --python .venv\Scripts\python.exe`
- Setting `HF_HOME` alone is **not** enough to relocate downloads. `HF_HUB_CACHE` and
  `TRANSFORMERS_CACHE` take precedence, and if the account has persistent user-level
  values for them, weights land there instead. `env.ps1` overrides all four
  per-process so the user-level vars other projects rely on stay untouched.
- The guard's degradation level is the **peak across every resource** — VRAM, GPU
  util, RAM, CPU, and the disk holding `data_dir` — not VRAM alone. At level >= 1 all
  cold-path work is deferred (re-queued with backoff, not dropped), so a box at 89%
  RAM or a >88%-full drive delays assessments with the GPU completely idle. Check
  `/stats` `resources` before blaming the code.
