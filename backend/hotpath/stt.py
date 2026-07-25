"""Hot-path STT stage — wraps the Faster-Whisper managed model.

Turbo optimizes the live turn for speed; the cold path re-analyzes audio for
scoring later. Import of numpy/faster-whisper is deferred to call time so the app
runs without the models group installed.
"""

from __future__ import annotations

import math

from backend.core.logging import get_logger
from backend.serving.adapters import WhisperSTTModel

log = get_logger("stt")


class WhisperSTTStage:
    def __init__(self, model: WhisperSTTModel):
        self._model = model

    def available(self) -> bool:
        return self._model.available() and self._model.model is not None

    async def transcribe(self, pcm: bytes, sample_rate: int) -> tuple[str, float]:
        if self._model.model is None:
            raise RuntimeError("Whisper model not loaded — enable COACH_LOAD_MODELS")
        import numpy as np

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, info = self._model.model.transcribe(audio, language="en", beam_size=1)
        texts: list[str] = []
        logprobs: list[float] = []
        for seg in segments:
            texts.append(seg.text)
            if getattr(seg, "avg_logprob", None) is not None:
                logprobs.append(seg.avg_logprob)
        text = "".join(texts).strip()
        # Map avg log-prob (~-1..0) to a rough 0..1 confidence.
        conf = float(math.exp(sum(logprobs) / len(logprobs))) if logprobs else 0.0
        return text, min(1.0, max(0.0, conf))
