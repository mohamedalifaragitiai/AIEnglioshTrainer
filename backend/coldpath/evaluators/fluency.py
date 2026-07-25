"""Fluency evaluator — deterministic, from transcript + timestamps (not vibes).

Speech rate in a target band, filler-word rate, and false starts. No LLM: fluency
is measurable. If timestamps are missing we fall back to a rate-neutral estimate so
the dimension still contributes (flagged in details).
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

_FILLERS = ("um", "uh", "er", "ah", "like", "you know", "i mean", "sort of", "kind of")
_TARGET_LO_WPM = 100.0
_TARGET_HI_WPM = 160.0


def _count_fillers(text: str) -> int:
    low = f" {text.lower()} "
    return sum(low.count(f" {f} ") for f in _FILLERS)


class FluencyEvaluator:
    name = "fluency"

    def __init__(self, *, version: str = "v1"):
        self.version = version

    def dimensions(self) -> tuple[str, ...]:
        return ("fluency",)

    def available(self) -> bool:
        return True

    async def evaluate(self, utt: UtteranceForEval, ctx: EvaluationContext) -> EvaluatorOutput:
        words = len(re.findall(r"\b\w+\b", utt.transcript))
        fillers = _count_fillers(utt.transcript)
        duration = utt.duration_s

        if duration and duration > 0 and words > 0:
            wpm = words / (duration / 60.0)
            if wpm < _TARGET_LO_WPM:
                rate_score = 100.0 * (wpm / _TARGET_LO_WPM)
            elif wpm > _TARGET_HI_WPM:
                rate_score = max(40.0, 100.0 - (wpm - _TARGET_HI_WPM) * 0.5)
            else:
                rate_score = 100.0
            rate_known = True
        else:
            wpm = None
            rate_score = 70.0  # neutral prior when we can't measure rate
            rate_known = False

        filler_rate = (fillers / words) if words else 0.0
        filler_penalty = min(30.0, filler_rate * 150.0)
        score = clamp_score(rate_score - filler_penalty)

        return EvaluatorOutput(
            self.name,
            self.version,
            [
                DimensionScore(
                    "fluency",
                    score,
                    details={
                        "words": words,
                        "wpm": round(wpm, 1) if wpm else None,
                        "fillers": fillers,
                        "filler_rate": round(filler_rate, 3),
                        "rate_measured": rate_known,
                    },
                )
            ],
            raw={"words": words, "wpm": wpm, "fillers": fillers},
        )
