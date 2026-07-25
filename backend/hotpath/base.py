"""Hot-path stage contracts and turn types.

The live loop is a fixed pipeline: STT -> single LLM dialogue call -> streaming
TTS. Each stage is a small Protocol so the pipeline can run with real models or
with fakes (tests, profiling) unchanged. Nothing here imports a model.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class HotEventKind(StrEnum):
    PARTIAL = "partial"    # interim transcript
    FINAL = "final"        # finalized user transcript
    REPLY = "reply"        # coach reply text
    AUDIO = "audio"        # a chunk of TTS audio (PCM16 bytes)
    TIMINGS = "timings"    # end-of-turn stage breakdown
    ERROR = "error"


@dataclass
class TurnTimings:
    stt_ms: float = 0.0
    llm_ms: float = 0.0
    tts_first_ms: float = 0.0      # from TTS start to first chunk
    first_audio_ms: float = 0.0    # from turn start to first chunk (the budget)
    tts_total_ms: float = 0.0
    degraded: bool = False

    def as_dict(self) -> dict:
        return {
            "stt_ms": round(self.stt_ms, 1),
            "llm_ms": round(self.llm_ms, 1),
            "tts_first_ms": round(self.tts_first_ms, 1),
            "first_audio_ms": round(self.first_audio_ms, 1),
            "tts_total_ms": round(self.tts_total_ms, 1),
            "degraded": self.degraded,
        }


@dataclass
class HotEvent:
    kind: HotEventKind
    text: str | None = None
    audio: bytes | None = None
    timings: TurnTimings | None = None
    meta: dict = field(default_factory=dict)


@runtime_checkable
class STTStage(Protocol):
    def available(self) -> bool: ...
    async def transcribe(self, pcm: bytes, sample_rate: int) -> tuple[str, float]: ...


@runtime_checkable
class DialogueStage(Protocol):
    async def reply(self, transcript: str, history: list[dict[str, str]]) -> str: ...
    def reply_stream(
        self, transcript: str, history: list[dict[str, str]]
    ) -> AsyncIterator[str]: ...


@runtime_checkable
class TTSStage(Protocol):
    def available(self) -> bool: ...
    def synthesize_stream(self, text: str) -> AsyncIterator[bytes]: ...
