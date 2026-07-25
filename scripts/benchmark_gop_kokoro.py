"""Benchmark the GOP (wav2vec2) and Kokoro TTS models on real weights.

Measures load time, resident VRAM, and inference latency for each, using the same
adapters the app uses. Reports honestly if a model can't load. Run after
`setup_models.py --download` and installing torch/transformers/kokoro.

Run:  COACH_LOAD_MODELS=true uv run python scripts/benchmark_gop_kokoro.py
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import wave

from backend.coldpath.pronunciation.gop import GOPScorer
from backend.core.resource_guard import PsutilNvmlSampler
from backend.hotpath.tts import KokoroTTSStage
from backend.serving.adapters import KokoroTTSModel, Wav2Vec2GOPModel
from config.settings import get_settings


def _vram_gb(sampler: PsutilNvmlSampler) -> float | None:
    r = sampler.sample().get("vram")
    if r is None or not sampler.vram_total_bytes:
        return None
    return r * sampler.vram_total_bytes / 1e9


def _write_test_wav(seconds: float) -> str:
    import numpy as np

    path = tempfile.mktemp(suffix=".wav")
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes((np.random.randn(int(16000 * seconds)) * 300).astype("int16").tobytes())
    return path


async def main() -> int:
    s = get_settings()
    sampler = PsutilNvmlSampler(disk_path=".")
    print("\n=== GOP + Kokoro benchmark ===")
    base = _vram_gb(sampler)
    print(f"VRAM baseline: {base:.2f} GB" if base is not None else "VRAM baseline: N/A")

    try:
        import torch

        print(f"torch {torch.__version__} | cuda_available={torch.cuda.is_available()} "
              f"| device={torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu'}")
    except Exception as exc:  # noqa: BLE001
        print(f"torch import failed: {exc}")

    # --- GOP (wav2vec2) ---
    gop = Wav2Vec2GOPModel(s)
    print(f"\nGOP available: {gop.available()}")
    if gop.available():
        try:
            b = _vram_gb(sampler)
            t = time.perf_counter()
            await gop.load()
            load_s = time.perf_counter() - t
            a = _vram_gb(sampler)
            wav = _write_test_wav(3.0)
            scorer = GOPScorer(gop)
            scorer.score(wav)  # warmup
            ts = []
            score = 0.0
            for _ in range(5):
                t = time.perf_counter()
                score, _ = scorer.score(wav)
                ts.append((time.perf_counter() - t) * 1000)
            ts.sort()
            os.remove(wav)
            dv = f"+{a - b:.2f}" if (a is not None and b is not None) else "?"
            print(f"GOP: load {load_s:.2f}s | VRAM {dv} GB | score p50 "
                  f"{ts[len(ts) // 2]:.0f}ms (3s clip) | sample_score {score:.1f}/100")
        except Exception as exc:  # noqa: BLE001
            print(f"GOP FAILED: {exc}")

    # --- Kokoro TTS ---
    tts = KokoroTTSModel(s)
    print(f"\nKokoro available: {tts.available()}")
    if tts.available():
        try:
            b = _vram_gb(sampler)
            t = time.perf_counter()
            await tts.load()
            load_s = time.perf_counter() - t
            a = _vram_gb(sampler)
            stage = KokoroTTSStage(tts)
            text = "Hello, let's practice speaking English together today."

            async def synth():
                t0 = time.perf_counter()
                first = None
                nbytes = 0
                async for chunk in stage.synthesize_stream(text):
                    if first is None:
                        first = (time.perf_counter() - t0) * 1000
                    nbytes += len(chunk)
                return first, (time.perf_counter() - t0) * 1000, nbytes

            await synth()  # warmup
            first, total, nbytes = await synth()
            audio_s = nbytes / 2 / 24000
            rtf = (total / 1000) / audio_s if audio_s else 0
            dv = f"+{a - b:.2f}" if (a is not None and b is not None) else "?"
            print(f"Kokoro: load {load_s:.2f}s | VRAM {dv} GB | first_chunk "
                  f"{first:.0f}ms | total {total:.0f}ms for {audio_s:.1f}s audio | RTF {rtf:.2f}")
        except Exception as exc:  # noqa: BLE001
            print(f"Kokoro FAILED: {exc}")

    if hasattr(sampler, "shutdown"):
        sampler.shutdown()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
