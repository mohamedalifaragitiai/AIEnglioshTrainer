#!/usr/bin/env bash
# Launch a vLLM OpenAI-compatible server for the coach — run inside WSL2 (Ubuntu)
# on Windows, or on any Linux host with an NVIDIA GPU. vLLM has no native Windows
# build; the FastAPI app stays on Windows and talks to this over localhost.
#
# Usage (from the repo root, inside WSL):
#   bash scripts/run_vllm.sh                                  # Qwen3-8B @ :8001
#   bash scripts/run_vllm.sh Qwen/Qwen3-8B 8001 0.68          # model port gpu-util
#   bash scripts/run_vllm.sh Qwen/Qwen3-8B-AWQ 8001 0.55      # quantized, less VRAM
#
# Co-hosting hot 8B + cold 14B: run this twice on two ports (e.g. 8001 and 8002)
# and set COACH_VLLM_BASE_URL to the hot one; or serve one model and point both
# COACH_VLLM_HOT_MODEL and COACH_VLLM_COLD_MODEL at it (the single-model fallback).
set -euo pipefail

MODEL="${1:-Qwen/Qwen3-8B}"
PORT="${2:-8001}"
GPU_UTIL="${3:-0.68}"           # matches COACH_VLLM_VRAM_FRACTION
MAX_LEN="${4:-8192}"

echo "==> Checking GPU (needs NVIDIA driver on Windows + WSL CUDA passthrough)"
nvidia-smi -L || { echo "No GPU visible in WSL. Install the Windows NVIDIA driver and WSL CUDA."; exit 1; }

# One-time: uv + a venv with vLLM. On a Blackwell (sm_120) GPU you need a recent
# vLLM built against CUDA 12.8 torch; uv resolves the current release.
if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

VENV="$HOME/.vllm-venv"
if [ ! -d "$VENV" ]; then
  echo "==> Creating vLLM venv at $VENV"
  uv venv "$VENV" --python 3.12
  uv pip install --python "$VENV/bin/python" vllm
fi

echo "==> Serving $MODEL on 127.0.0.1:$PORT (gpu-util $GPU_UTIL, max-len $MAX_LEN)"
echo "    First run downloads the weights (multi-GB, one-time)."
exec "$VENV/bin/python" -m vllm.entrypoints.openai.api_server \
  --model "$MODEL" \
  --served-model-name "$MODEL" \
  --host 127.0.0.1 --port "$PORT" \
  --gpu-memory-utilization "$GPU_UTIL" \
  --max-model-len "$MAX_LEN"
