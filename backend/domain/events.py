"""Event contracts shared between the hot path and the cold path.

See ``references/architecture.md`` — the hot path emits ``UtteranceFinalized`` at
turn end; the cold-path worker (Phase 4) consumes it and, after scoring, emits
``AssessmentReady`` for the dashboard/report layer. Events are immutable and
carry only ids + primitives so subscribers can be idempotent and retry-safe.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UtteranceFinalized:
    utterance_id: str
    session_id: str
    user_id: str
    transcript: str
    stt_confidence: float | None
    start_ms: int | None
    end_ms: int | None
    audio_path: str | None = None


@dataclass(frozen=True)
class AssessmentReady:
    user_id: str
    session_id: str
    assessment_id: str
