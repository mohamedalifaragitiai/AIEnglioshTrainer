"""Pronunciation evaluator — real GOP when possible, proxy otherwise.

Prefers the resident wav2vec2 GOP over the learner's stored audio; falls back to the
STT-confidence proxy when the model isn't loaded or no audio was captured. Either
way it produces the ``pronunciation`` dimension. Never uses the LLM — transcripts
carry no acoustic detail.
"""

from __future__ import annotations

from backend.coldpath.evaluators.base import (
    DimensionScore,
    EvaluationContext,
    EvaluatorOutput,
    UtteranceForEval,
)
from backend.coldpath.pronunciation.gop import GOPScorer
from backend.coldpath.pronunciation.proxy import proxy_pronunciation
from backend.core.logging import get_logger

log = get_logger("pronunciation")


class PronunciationEvaluator:
    name = "pronunciation"

    def __init__(self, gop: GOPScorer | None = None, *, version: str = "v1"):
        self._gop = gop
        self.version = version

    def dimensions(self) -> tuple[str, ...]:
        return ("pronunciation",)

    def available(self) -> bool:
        return True  # always: proxy is available even with no model

    async def evaluate(self, utt: UtteranceForEval, ctx: EvaluationContext) -> EvaluatorOutput:
        if self._gop is not None and self._gop.available() and utt.audio_path:
            try:
                score, details = self._gop.score(utt.audio_path)
            except Exception as exc:  # noqa: BLE001 — degrade to proxy, never fail the job
                log.warning("gop_failed_fallback_proxy", error=str(exc))
                score, details = proxy_pronunciation(utt.stt_confidence)
        else:
            score, details = proxy_pronunciation(utt.stt_confidence)

        return EvaluatorOutput(
            self.name,
            self.version,
            [DimensionScore("pronunciation", score, details=details)],
            raw=details,
        )
