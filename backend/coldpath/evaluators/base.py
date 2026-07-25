"""Evaluator contract shared by every cold-path evaluator.

Input = finalized utterance + audio ref + context; output = typed per-dimension
scores (0-100) plus a raw payload stored verbatim in ``evaluator_outputs`` for
retroactive recompute/audit. One evaluator may produce several dimensions (the
batched LLM call does five at once). Adding an evaluator must not touch the hot
path — the worker runs whichever are registered and available.

See ``references/scoring.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class UtteranceForEval:
    utterance_id: str
    session_id: str
    user_id: str
    transcript: str
    audio_path: str | None = None
    stt_confidence: float | None = None
    start_ms: int | None = None
    end_ms: int | None = None

    @property
    def duration_s(self) -> float | None:
        if self.start_ms is not None and self.end_ms is not None and self.end_ms > self.start_ms:
            return (self.end_ms - self.start_ms) / 1000.0
        return None


@dataclass(frozen=True)
class EvaluationContext:
    prompt: str | None          # the coach's last prompt/instruction
    recent_turns: list[dict]    # rolling history [{role, content}, ...]
    learner_level: int
    scoring_model_version: str


@dataclass
class DimensionScore:
    dimension: str
    score: float                # 0-100
    details: dict = field(default_factory=dict)
    corrections: list | None = None
    suggestions: list | None = None


@dataclass
class EvaluatorOutput:
    evaluator: str
    version: str
    scores: list[DimensionScore]
    raw: dict = field(default_factory=dict)  # full payload -> evaluator_outputs


@runtime_checkable
class Evaluator(Protocol):
    name: str
    version: str

    def dimensions(self) -> tuple[str, ...]: ...
    def available(self) -> bool: ...
    async def evaluate(self, utt: UtteranceForEval, ctx: EvaluationContext) -> EvaluatorOutput: ...


def clamp_score(x: float) -> float:
    return max(0.0, min(100.0, float(x)))
