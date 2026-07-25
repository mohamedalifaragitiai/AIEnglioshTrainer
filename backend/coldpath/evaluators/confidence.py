"""Confidence evaluator — a delivery-steadiness proxy (acceptable for v1).

Steadiness of delivery: hesitation/filler pattern and self-corrections. A true
acoustic measure (volume/pitch stability) belongs to the audio pipeline later; the
proxy here is deterministic and derived from the transcript + STT confidence.
"""

from __future__ import annotations

import re

from backend.coldpath.evaluators.base import (
    DimensionScore,
    EvaluationContext,
    EvaluatorOutput,
    UtteranceForEval,
    clamp_score,
)

_HESITATIONS = ("um", "uh", "er", "ah")
_SELF_CORRECTIONS = ("i mean", "sorry", "no wait", "actually no", "let me")


def _count(text: str, phrases) -> int:
    low = f" {text.lower()} "
    return sum(low.count(f" {p} ") for p in phrases)


class ConfidenceEvaluator:
    name = "confidence"

    def __init__(self, *, version: str = "v1"):
        self.version = version

    def dimensions(self) -> tuple[str, ...]:
        return ("confidence",)

    def available(self) -> bool:
        return True

    async def evaluate(self, utt: UtteranceForEval, ctx: EvaluationContext) -> EvaluatorOutput:
        words = max(1, len(re.findall(r"\b\w+\b", utt.transcript)))
        hesitations = _count(utt.transcript, _HESITATIONS)
        corrections = _count(utt.transcript, _SELF_CORRECTIONS)

        base = 75.0
        hes_penalty = min(30.0, (hesitations / words) * 200.0)
        corr_penalty = min(20.0, corrections * 6.0)
        # A shaky STT confidence hints at unsteady delivery too.
        conf_bonus = 0.0
        if utt.stt_confidence is not None:
            conf_bonus = (utt.stt_confidence - 0.7) * 30.0  # +/- around a 0.7 anchor

        score = clamp_score(base - hes_penalty - corr_penalty + conf_bonus)
        return EvaluatorOutput(
            self.name,
            self.version,
            [
                DimensionScore(
                    "confidence",
                    score,
                    details={
                        "hesitations": hesitations,
                        "self_corrections": corrections,
                        "stt_confidence": utt.stt_confidence,
                    },
                )
            ],
            raw={"hesitations": hesitations, "self_corrections": corrections},
        )
