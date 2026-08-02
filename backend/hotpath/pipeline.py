"""The hot-path pipeline: one learner turn, streamed, guard-gated, <300ms budget.

``run_turn`` is an async generator yielding :class:`HotEvent`s (final transcript,
reply text, then audio chunks, then a timings summary). Both the WebSocket loop and
``profile_hotpath.py`` consume the same stream, so what's measured is what ships.

The guard gates each stage but the hot path is never blocked — a live speaker is
waiting — so degradation only *shapes* the work (shorter reply, flag set), it never
stalls. The single LLM call carries the reply; TTS streams so the first audio chunk
leaves as soon as the first phrase is ready. At turn end an ``UtteranceFinalized``
event is published for the cold path.
"""

from __future__ import annotations

import wave
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

from backend.core import metrics
from backend.core.event_bus import EventBus
from backend.core.logging import get_logger
from backend.core.resource_guard import ResourceEstimate, ResourceGuard
from backend.domain.events import UtteranceFinalized
from backend.domain.models import Role
from backend.hotpath.base import (
    DialogueStage,
    HotEvent,
    HotEventKind,
    STTStage,
    TTSStage,
    TurnTimings,
)
from backend.hotpath.dialogue import speakable_text
from backend.persistence.repositories import UtteranceRepository
from config.settings import Settings

log = get_logger("hotpath")


@dataclass
class TurnContext:
    session_id: str
    user_id: str
    history: list[dict[str, str]] = field(default_factory=list)
    system_prompt: str | None = None  # level/topic-aware coach persona
    # Reading practice wants the transcript and nothing else: the learner is
    # reading a fixed passage, so a conversational reply is noise in their
    # history and a needless LLM+TTS run on a box with one GPU.
    reply: bool = True
    # The coach's voice for this learner, semantic ("female"/"male").
    voice: str | None = None


class HotPathPipeline:
    def __init__(
        self,
        stt: STTStage,
        dialogue: DialogueStage,
        tts: TTSStage,
        *,
        guard: ResourceGuard,
        settings: Settings,
        event_bus: EventBus | None = None,
        utterances: UtteranceRepository | None = None,
    ):
        self.stt = stt
        self.dialogue = dialogue
        self.tts = tts
        self.guard = guard
        self.settings = settings
        self.bus = event_bus
        self.utterances = utterances

    async def run_turn(self, pcm: bytes, ctx: TurnContext) -> AsyncIterator[HotEvent]:
        sr = self.settings.hotpath_sample_rate
        timings = TurnTimings()
        t0 = perf_counter()

        # --- STT ---
        adm = await self.guard.acquire(ResourceEstimate(gpu_util_frac=0.3), "hot")
        timings.degraded |= adm.kind == "degraded"
        t = perf_counter()
        try:
            transcript, confidence = await self.stt.transcribe(pcm, sr)
        except Exception as exc:  # noqa: BLE001
            metrics.hotpath_turns_total.labels("error").inc()
            log.error("stt_failed", error=str(exc))
            yield HotEvent(HotEventKind.ERROR, text=f"stt: {exc}")
            return
        timings.stt_ms = (perf_counter() - t) * 1000
        metrics.hotpath_stage_seconds.labels("stt").observe(timings.stt_ms / 1000)
        yield HotEvent(HotEventKind.FINAL, text=transcript, meta={"confidence": confidence})

        if not ctx.reply:
            # Still persist and publish, so the cold path scores the attempt and
            # it counts towards the learner's history. TIMINGS is still emitted
            # because the socket contract is that every 'end' is closed out.
            await self._finalize(pcm, transcript, confidence, "", ctx)
            metrics.hotpath_turns_total.labels("degraded" if timings.degraded else "ok").inc()
            yield HotEvent(HotEventKind.TIMINGS, timings=timings)
            return

        # --- Dialogue -> TTS, streamed sentence-by-sentence ---
        # The reply streams a sentence at a time; each is spoken immediately, so the
        # first audio leaves after the first phrase — not the whole reply. TTS runs
        # while the LLM is still generating the rest.
        await self.guard.acquire(ResourceEstimate(gpu_util_frac=0.2), "hot")
        llm_start = perf_counter()
        first_token_at: float | None = None
        first_chunk_at: float | None = None
        reply_parts: list[str] = []
        try:
            async for phrase in self.dialogue.reply_stream(
                transcript, ctx.history, system_prompt=ctx.system_prompt
            ):
                if first_token_at is None:
                    first_token_at = perf_counter()
                    timings.llm_ms = (first_token_at - llm_start) * 1000  # time-to-first-sentence
                    metrics.hotpath_stage_seconds.labels("llm").observe(timings.llm_ms / 1000)
                reply_parts.append(phrase)
                yield HotEvent(HotEventKind.REPLY, text=phrase, meta={"partial": True})
                # Speak the phrase, but never read emojis/symbols aloud.
                speech = speakable_text(phrase)
                if not speech:
                    continue
                async for chunk in self.tts.synthesize_stream(speech, voice=ctx.voice):
                    if first_chunk_at is None:
                        first_chunk_at = perf_counter()
                        timings.tts_first_ms = (first_chunk_at - first_token_at) * 1000
                        timings.first_audio_ms = (first_chunk_at - t0) * 1000
                        metrics.hotpath_first_audio_seconds.observe(timings.first_audio_ms / 1000)
                        metrics.hotpath_stage_seconds.labels("tts_first").observe(
                            timings.tts_first_ms / 1000
                        )
                    yield HotEvent(HotEventKind.AUDIO, audio=chunk)
        except Exception as exc:  # noqa: BLE001
            metrics.hotpath_turns_total.labels("error").inc()
            log.error("dialogue_or_tts_failed", error=str(exc))
            yield HotEvent(HotEventKind.ERROR, text=f"llm/tts: {exc}")
            return

        reply = " ".join(reply_parts).strip()
        timings.tts_total_ms = (perf_counter() - llm_start) * 1000
        metrics.hotpath_stage_seconds.labels("tts_total").observe(timings.tts_total_ms / 1000)

        # --- persist + emit (turn is already returning to the learner) ---
        await self._finalize(pcm, transcript, confidence, reply, ctx)

        metrics.hotpath_turns_total.labels("degraded" if timings.degraded else "ok").inc()
        if timings.first_audio_ms > self.settings.first_audio_budget_ms:
            log.warning(
                "first_audio_over_budget",
                first_audio_ms=round(timings.first_audio_ms, 1),
                budget_ms=self.settings.first_audio_budget_ms,
            )
        yield HotEvent(HotEventKind.TIMINGS, timings=timings)

    async def _finalize(
        self,
        pcm: bytes,
        transcript: str,
        confidence: float,
        reply: str,
        ctx: TurnContext,
    ) -> None:
        """Persist the learner + coach utterances and publish UtteranceFinalized.

        Best-effort: persistence/audio problems must not fail the turn (already
        delivered). The cold path re-analyzes the stored audio for scoring.
        """
        audio_path = self._write_audio(pcm, ctx)
        utterance_id = "utt_unpersisted"
        try:
            if self.utterances is not None:
                learner = self.utterances.add(
                    ctx.session_id,
                    ctx.user_id,
                    Role.LEARNER,
                    transcript=transcript,
                    audio_path=audio_path,
                    stt_confidence=confidence,
                )
                utterance_id = learner.utterance_id
                # No coach turn in reading mode: nothing was said back, and a
                # blank coach utterance would show up as an empty chat bubble.
                if reply:
                    self.utterances.add(
                        ctx.session_id, ctx.user_id, Role.COACH, transcript=reply
                    )
        except Exception as exc:  # noqa: BLE001
            log.error("utterance_persist_failed", error=str(exc))

        if self.bus is not None:
            self.bus.publish(
                UtteranceFinalized(
                    utterance_id=utterance_id,
                    session_id=ctx.session_id,
                    user_id=ctx.user_id,
                    transcript=transcript,
                    stt_confidence=confidence,
                    start_ms=None,
                    end_ms=None,
                    audio_path=audio_path,
                )
            )

    def _write_audio(self, pcm: bytes, ctx: TurnContext) -> str | None:
        if self.settings.audio_dir is None:
            return None
        try:
            audio_dir = Path(self.settings.audio_dir)
            audio_dir.mkdir(parents=True, exist_ok=True)
            path = audio_dir / f"{ctx.session_id}_{perf_counter_ns_hex()}.wav"
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.settings.hotpath_sample_rate)
                wf.writeframes(pcm)
            return str(path)
        except Exception as exc:  # noqa: BLE001
            log.error("audio_write_failed", error=str(exc))
            return None


def perf_counter_ns_hex() -> str:
    from time import perf_counter_ns

    return f"{perf_counter_ns():x}"
