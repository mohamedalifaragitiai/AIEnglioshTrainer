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
fi
# --torch-backend=auto detects the installed NVIDIA driver's CUDA version and picks
# matching wheels — avoids pulling a CUDA-13 build onto a CUDA-12.x driver
# ("driver too old"). Set VLLM_VERSION to pin a build whose *kernels* also target
# your CUDA (recent vLLM ships CUDA-13-only wheels needing driver 580+). Idempotent.
if ! "$VENV/bin/python" -c "import vllm" 2>/dev/null; then
  SPEC="vllm${VLLM_VERSION:+==$VLLM_VERSION}"
  echo "==> Installing $SPEC (torch backend auto-matched to the driver)"
  uv pip install --python "$VENV/bin/python" --torch-backend=auto "$SPEC"
  # Older vLLM (pinned for CUDA compat) predates transformers 5.x, which removed
  # tokenizer internals it relies on — cap it at 4.x when pinning an old vLLM.
  if [ -n "${VLLM_VERSION:-}" ]; then
    uv pip install --python "$VENV/bin/python" "transformers<5"
  fi
fi

# Fail fast with a clear message if the CUDA runtime doesn't match the driver,
# before paying for a multi-GB model download.
"$VENV/bin/python" -c "import torch, vllm; print('CUDA CHECK: torch', torch.__version__, '| cuda', torch.version.cuda, '| vllm', vllm.__version__)"

echo "==> Serving $MODEL on 127.0.0.1:$PORT (gpu-util $GPU_UTIL, max-len $MAX_LEN)"
echo "    First run downloads the weights (multi-GB, one-time)."
# --enforce-eager disables torch.compile/CUDA-graph capture, which otherwise needs a
# C compiler (gcc) at load. Set VLLM_EAGER=0 to enable compilation if gcc is present
# (build-essential) for maximum throughput.
EAGER_FLAG="--enforce-eager"
[ "${VLLM_EAGER:-1}" = "0" ] && EAGER_FLAG=""

exec "$VENV/bin/python" -m vllm.entrypoints.openai.api_server \
  --model "$MODEL" \
  --served-model-name "$MODEL" \
  --host 127.0.0.1 --port "$PORT" \
  --gpu-memory-utilization "$GPU_UTIL" \
  --max-model-len "$MAX_LEN" \
  $EAGER_FLAG
