"""Hot-path TTS stage — wraps Kokoro, streaming audio chunks.

Streaming matters for the budget: the first chunk should leave as soon as the first
phrase is synthesized, not after the whole reply. Kokoro yields per-segment audio;
we convert each to PCM16 bytes and yield immediately. Import is deferred to call
time so the app runs without the models group installed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from backend.serving.adapters import KokoroTTSModel

# Semantic name -> Kokoro voice pack. The mapping lives here, not in the
# database: a stored "am_michael" would be meaningless the day the pack is
# swapped, while "male" survives the model changing underneath it.
VOICES: dict[str, str] = {
    "female": "af_heart",
    "male": "am_michael",
}
DEFAULT_VOICE = "female"


def voice_pack(name: str | None) -> str:
    """Kokoro pack for a semantic voice, falling back rather than failing.

    An unknown value must not break a turn: the learner would lose their reply
    over a preference, which is the wrong trade.
    """
    return VOICES.get((name or DEFAULT_VOICE).lower(), VOICES[DEFAULT_VOICE])


class KokoroTTSStage:
    def __init__(self, model: KokoroTTSModel, *, voice: str = DEFAULT_VOICE):
        self._model = model
        self._voice = voice

    def available(self) -> bool:
        return self._model.available() and self._model.pipeline is not None

    async def synthesize_stream(
        self, text: str, *, voice: str | None = None
    ) -> AsyncIterator[bytes]:
        if self._model.pipeline is None:
            raise RuntimeError("Kokoro pipeline not loaded — enable COACH_LOAD_MODELS")
        import asyncio

        import numpy as np

        # Kokoro's pipeline is a blocking (sync) generator. Drive it on a worker
        # thread and hand PCM chunks to the async consumer via a threadsafe queue, so
        # synthesis never stalls the event loop and overlaps with LLM streaming.
        pack = voice_pack(voice or self._voice)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        done = object()

        def _produce() -> None:
            try:
                for _gs, _ps, audio in self._model.pipeline(text, voice=pack):
                    a = (
                        audio.detach().cpu().numpy()
                        if hasattr(audio, "detach")
                        else np.asarray(audio, dtype=np.float32)
                    )
                    pcm16 = (np.clip(a, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
                    loop.call_soon_threadsafe(queue.put_nowait, pcm16)
            except Exception as exc:  # noqa: BLE001 — surface to the consumer
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, done)

        task = loop.run_in_executor(None, _produce)
        try:
            while True:
                item = await queue.get()
                if item is done:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            await task
