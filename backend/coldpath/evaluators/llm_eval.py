"""Batched LLM evaluator — grammar, vocabulary, listening, coherence, relevance.

ONE structured LLM call on the cold-path 14B (never one call per dimension: that
wastes latency and VRAM). Returns strict JSON which we parse into per-dimension
scores plus corrections/suggestions. Runs on the cold path, so latency is
irrelevant and the guard may defer it under pressure. The LLM never judges audio.
"""

from __future__ import annotations

import json

from backend.coldpath.evaluators.base import (
    DimensionScore,
    EvaluationContext,
    EvaluatorOutput,
    UtteranceForEval,
    clamp_score,
)
from backend.core.logging import get_logger
from backend.serving.llm_client import VLLMClient

log = get_logger("llm_eval")

_DIMENSIONS = ("grammar", "vocabulary", "listening", "coherence", "relevance")

_SYSTEM = (
    "You are a strict English-assessment engine. Score a learner's spoken turn on "
    "five dimensions, each 0-100. Return ONLY a JSON object, no prose."
)

_RUBRIC = (
    "grammar: fewer/severe errors (tense, agreement) lower the score more than "
    "articles/prepositions. vocabulary: diversity + sophistication, penalize "
    "repetition. listening: how well the answer addresses the coach's prompt. "
    "coherence: logical flow, discourse markers, on-topic development. relevance: "
    "completeness and topic match to the prompt."
)


def _build_prompt(utt: UtteranceForEval, ctx: EvaluationContext) -> list[dict[str, str]]:
    schema = (
        '{"grammar":{"score":int,"errors":[{"text":str,"correction":str,"type":str}]},'
        '"vocabulary":{"score":int,"suggestions":[str]},'
        '"listening":{"score":int},"coherence":{"score":int},'
        '"relevance":{"score":int},"overall_notes":str}'
    )
    user = (
        f"Coach prompt: {ctx.prompt or '(open conversation)'}\n"
        f"Learner level (0-5): {ctx.learner_level}\n"
        f"Learner said: \"{utt.transcript}\"\n\n"
        f"Rubric: {_RUBRIC}\n"
        f"Respond with exactly this JSON shape: {schema}"
    )
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of the model's reply, tolerating stray prose."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON object in LLM reply: {text[:120]!r}")
    return json.loads(text[start : end + 1])


class LLMEvaluator:
    name = "llm_batch"

    def __init__(self, client: VLLMClient, *, version: str = "v1", max_tokens: int = 400):
        self._client = client
        self.version = version
        self._max_tokens = max_tokens

    def dimensions(self) -> tuple[str, ...]:
        return _DIMENSIONS

    def available(self) -> bool:
        return bool(self._client.base_url)

    async def evaluate(self, utt: UtteranceForEval, ctx: EvaluationContext) -> EvaluatorOutput:
        messages = _build_prompt(utt, ctx)
        reply = await self._client.chat(
            messages, path="cold", max_tokens=self._max_tokens, temperature=0.0
        )
        data = _extract_json(reply)

        scores: list[DimensionScore] = []
        for dim in _DIMENSIONS:
            node = data.get(dim, {})
            score = clamp_score(node.get("score", 0))
            corrections = node.get("errors") if dim == "grammar" else None
            suggestions = node.get("suggestions") if dim == "vocabulary" else None
            scores.append(
                DimensionScore(
                    dimension=dim,
                    score=score,
                    details={k: v for k, v in node.items() if k != "score"},
                    corrections=corrections,
                    suggestions=suggestions,
                )
            )
        return EvaluatorOutput(self.name, self.version, scores, raw=data)
