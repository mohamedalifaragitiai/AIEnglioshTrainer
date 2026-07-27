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
        f"Respond with exactly this JSON shape: {schema}\n"
        # The reply used to run past max_tokens and arrive as truncated JSON, which
        # cost the whole batch. Bounding the arrays keeps it comfortably inside.
        "Hard limits: at most 3 entries in errors, at most 5 in suggestions, and "
        "overall_notes under 20 words. Output minified JSON on a single line."
    )
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]


def _repair_truncated(chunk: str) -> str:
    """Close brackets left open by a reply that hit the token ceiling.

    A cut-off reply is the common failure here, not malformed syntax: the model is
    partway through ``errors`` when generation stops. Dropping to the last complete
    element and closing the structure recovers the scores instead of losing all five
    dimensions to a JSONDecodeError.
    """
    # Walk the text tracking structure, ignoring braces inside strings.
    stack: list[str] = []
    in_str = False
    escape = False
    last_safe = None  # index just past the last completed top-level-ish value
    for i, ch in enumerate(chunk):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
        elif ch == "," and len(stack) <= 2:
            last_safe = i
    if in_str or not stack:
        # Mid-string, or already balanced: fall back to the last comma boundary.
        if last_safe is None:
            raise ValueError("truncated JSON with no recoverable boundary")
        return _repair_truncated(chunk[:last_safe])
    closing = "".join("}" if b == "{" else "]" for b in reversed(stack))
    return chunk + closing


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of the model's reply, tolerating stray prose
    and a reply that was cut short by the token ceiling."""
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in LLM reply: {text[:120]!r}")
    end = text.rfind("}")
    if end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass  # fall through to the truncation repair
    candidate = text[start:]
    repaired = _repair_truncated(candidate)
    data = json.loads(repaired)
    log.warning("llm_json_repaired", recovered_keys=sorted(data))
    return data


class LLMEvaluator:
    name = "llm_batch"

    # 400 was not enough headroom: replies hit the ceiling mid-JSON and the whole
    # batch was lost to a parse error. The prompt now caps the arrays too.
    def __init__(self, client: VLLMClient, *, version: str = "v1", max_tokens: int = 700):
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
        skipped: list[str] = []
        for dim in _DIMENSIONS:
            node = data.get(dim)
            if not isinstance(node, dict):
                skipped.append(dim)
                continue
            # A dimension the model did not actually score must be OMITTED, not
            # recorded as 0. Defaulting to 0 invented a failing grade out of a
            # missing key, and the aggregate renormalizes over present dimensions
            # anyway — so skipping costs coverage, not accuracy.
            raw_score = node.get("score")
            if not isinstance(raw_score, int | float) or isinstance(raw_score, bool):
                skipped.append(dim)
                continue
            corrections = node.get("errors") if dim == "grammar" else None
            suggestions = node.get("suggestions") if dim == "vocabulary" else None
            scores.append(
                DimensionScore(
                    dimension=dim,
                    score=clamp_score(raw_score),
                    details={k: v for k, v in node.items() if k != "score"},
                    corrections=corrections,
                    suggestions=suggestions,
                )
            )
        if skipped:
            log.warning("llm_dimensions_unscored", skipped=skipped)
        return EvaluatorOutput(self.name, self.version, scores, raw=data)
