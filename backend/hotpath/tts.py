"""Hot-path TTS stage — wraps Kokoro, streaming audio chunks.

Streaming matters for the budget: the first chunk should leave as soon as the first
phrase is synthesized, not after the whole reply. Kokoro yields per-segment audio;
we convert each to PCM16 bytes and yield immediately. Import is deferred to call
time so the app runs without the models group installed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from backend.serving.adapters import KokoroTTSModel


class KokoroTTSStage:
    def __init__(self, model: KokoroTTSModel, *, voice: str = "af_heart"):
        self._model = model
        self._voice = voice

    def available(self) -> bool:
        return self._model.available() and self._model.pipeline is not None

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        if self._model.pipeline is None:
            raise RuntimeError("Kokoro pipeline not loaded — enable COACH_LOAD_MODELS")
        import numpy as np

        # Kokoro yields (graphemes, phonemes, audio_float32) per segment.
        for _gs, _ps, audio in self._model.pipeline(text, voice=self._voice):
            # Kokoro yields a torch Tensor; bring it to CPU numpy before packing.
            if hasattr(audio, "detach"):
                audio = audio.detach().cpu().numpy()
            audio = np.asarray(audio, dtype=np.float32)
            pcm16 = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
            yield pcm16.tobytes()
