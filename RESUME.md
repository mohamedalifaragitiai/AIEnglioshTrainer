# Resume after a reboot

Everything is committed. The two servers (app + vLLM) stop on shutdown; the
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

## Machine-specific notes (why the above is the way it is)

- **Driver 577.03 = CUDA 12.9.** Latest vLLM (0.26) ships CUDA-13-only wheels
  (needs driver 580+), so vLLM is pinned to **0.11.0** (torch 2.8+cu129). Its kernels
  match the driver; `transformers` must be `<5` (5.x broke its tokenizer path).
- **torch / transformers / kokoro are installed in `.venv` but NOT in
  `pyproject`/`uv.lock`** (host/CUDA-specific). Run app/model scripts with
  `.venv/Scripts/python.exe`, never `uv run`, or they get removed.
- **WSL DNS** works via the default tunneled resolver — don't set a manual
  `/etc/resolv.conf` (that breaks it here).
- Models on disk: STT/GOP/Kokoro in `models/`; Qwen3-8B-AWQ in the WSL HF cache.
- **Isolation:** all in `D:/AI_English_Coach/english-coach` + WSL `~/.vllm-venv`.
  Nothing shared with other projects; app on 8000, vLLM on 8001.

## Verify it's live

```bash
curl -s http://127.0.0.1:8000/stats            # VRAM/GPU/CPU + models_loaded 5
curl -s http://127.0.0.1:8000/models/llm/health  # {"healthy": true}
./.venv/Scripts/python.exe scripts/live_turn_check.py   # end-to-end voice turn
```
