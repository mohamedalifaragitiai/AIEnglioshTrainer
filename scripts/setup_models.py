"""One-time model setup — explicit, logged, and budget-checked.

Downloads are the ONLY network use in the whole system and must be deliberate. This
script defaults to ``--check`` (report the plan, deps, disk/VRAM budget, and vLLM
reachability — download nothing). Pass ``--download`` to actually fetch the resident
GPU models (STT + GOP + TTS) into ``models_dir``.

The LLMs (Qwen3-8B/14B) are NOT downloaded here: vLLM manages its own weights on its
host (native Linux/WSL2 on Windows). This script prints how to launch that server.

Run:
  uv run python scripts/setup_models.py            # check only (safe)
  uv sync --group models                           # install download deps first
  uv run python scripts/setup_models.py --download # fetch STT/GOP/TTS weights
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
from dataclasses import dataclass

from backend.core.logging import configure_logging, get_logger
from backend.core.resource_guard import PsutilNvmlSampler, ResourceGuard
from config.settings import get_settings

log = get_logger("setup_models")


@dataclass
class ModelSpec:
    kind: str
    repo_id: str
    approx_gb: float
    note: str


def _resident_models(settings) -> list[ModelSpec]:
    return [
        ModelSpec(
            "stt",
            "deepdml/faster-whisper-large-v3-turbo-ct2",
            1.6,
            f"Faster-Whisper {settings.stt_model} (CTranslate2). Hot path STT.",
        ),
        ModelSpec("gop", settings.gop_model, 1.3, "wav2vec2 phoneme CTC for GOP. Cold path."),
        ModelSpec("tts", settings.tts_model, 0.4, "Kokoro-82M TTS. Hot path, own process."),
    ]


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _free_gb(path: str) -> float:
    return shutil.disk_usage(path).free / 1e9


def check(settings) -> int:
    specs = _resident_models(settings)
    models_dir = settings.models_dir
    models_dir.mkdir(parents=True, exist_ok=True)

    print("\n=== AI English Coach — model setup (check) ===\n")
    print(f"models_dir: {models_dir}")
    free = _free_gb(str(models_dir))
    needed = sum(s.approx_gb for s in specs)
    print(f"disk free : {free:.1f} GB   |   resident models need ~{needed:.1f} GB\n")

    print("Resident GPU models (downloaded here):")
    for s in specs:
        print(f"  [{s.kind:>3}] {s.repo_id:<48} ~{s.approx_gb:>4.1f}GB  {s.note}")
    print("\nLLMs (NOT downloaded here — vLLM manages these on its own host):")
    print(f"  [llm] {settings.vllm_hot_model}  (hot dialogue)")
    print(f"  [llm] {settings.vllm_cold_model} (cold assessment)")

    print("\nDependency group 'models' installed?")
    for mod in ("huggingface_hub", "faster_whisper", "torch", "transformers", "kokoro"):
        status = "yes" if _installed(mod) else "NO  (uv sync --group models / see README)"
        print(f"  {mod:<16}: {status}")

    # VRAM budget under the 96% ceiling (via the guard).
    sampler = PsutilNvmlSampler(disk_path=str(models_dir))
    guard = ResourceGuard(sampler=sampler, settings=settings)
    guard.feed(sampler.sample())
    min_set = settings.stt_vram_gb + settings.gop_vram_gb + settings.tts_vram_gb
    fits, msg = guard.check_startup_budget(min_set)
    print("\nVRAM budget (guard):")
    print(f"  resident non-vLLM set (STT+GOP+TTS) ~= {min_set:.1f} GB")
    print(f"  {msg}")
    if hasattr(sampler, "shutdown"):
        sampler.shutdown()

    print("\nTo run the LLM server (native Linux/WSL2 on Windows):")
    print("  uv run vllm serve \\")
    print(f"    {settings.vllm_hot_model} \\")
    print(f"    --gpu-memory-utilization {settings.vllm_vram_fraction} \\")
    print("    --port 8001  --host 127.0.0.1")
    print("  # (co-host the 14B via a second --served-model-name / model as VRAM allows)\n")

    if free < needed:
        print(f"WARNING: only {free:.1f}GB free but ~{needed:.1f}GB needed for resident models.")
        return 1
    print("Check complete. Re-run with --download to fetch the resident weights.\n")
    return 0


def download(settings) -> int:
    if not _installed("huggingface_hub"):
        print("huggingface_hub not installed. Run:  uv sync --group models")
        return 1
    from huggingface_hub import snapshot_download

    specs = _resident_models(settings)
    models_dir = settings.models_dir
    models_dir.mkdir(parents=True, exist_ok=True)

    needed = sum(s.approx_gb for s in specs)
    free = _free_gb(str(models_dir))
    if free < needed * 1.1:
        log.error("insufficient_disk", free_gb=round(free, 1), needed_gb=round(needed, 1))
        print(f"Refusing to download: {free:.1f}GB free < ~{needed*1.1:.1f}GB needed (10% margin).")
        return 1

    for s in specs:
        log.info("download_start", kind=s.kind, repo_id=s.repo_id, approx_gb=s.approx_gb)
        print(f"Downloading [{s.kind}] {s.repo_id} (~{s.approx_gb}GB) ...")
        path = snapshot_download(repo_id=s.repo_id, cache_dir=str(models_dir))
        log.info("download_done", kind=s.kind, repo_id=s.repo_id, path=path)
        print(f"  -> {path}")

    print("\nResident weights fetched. Start vLLM (see --check output), then run with")
    print("COACH_LOAD_MODELS=true to load models through the guard at startup.\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Set up local models (check-first).")
    parser.add_argument("--download", action="store_true", help="actually fetch weights")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=False)
    return download(settings) if args.download else check(settings)


if __name__ == "__main__":
    raise SystemExit(main())
