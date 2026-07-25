"""Tests for cold-path evaluators (deterministic + batched LLM)."""

from __future__ import annotations

import json

import httpx
import pytest

from backend.coldpath.evaluators.base import EvaluationContext, UtteranceForEval
from backend.coldpath.evaluators.confidence import ConfidenceEvaluator
from backend.coldpath.evaluators.fluency import FluencyEvaluator
from backend.coldpath.evaluators.llm_eval import LLMEvaluator, _extract_json
from backend.coldpath.pronunciation.evaluator import PronunciationEvaluator
from backend.serving.llm_client import VLLMClient

CTX = EvaluationContext(prompt="Tell me about your day.", recent_turns=[], learner_level=2,
                        scoring_model_version="v1")


def _utt(transcript, **kw):
    return UtteranceForEval(
        utterance_id="u1", session_id="s1", user_id="abu_ali", transcript=transcript, **kw
    )


# --- fluency ---------------------------------------------------------------


async def test_fluency_with_timestamps_measures_rate():
    ev = FluencyEvaluator()
    out = await ev.evaluate(
        _utt("I really enjoy learning new things every single day", start_ms=0, end_ms=4000), CTX
    )
    ds = out.scores[0]
    assert ds.dimension == "fluency"
    assert ds.details["rate_measured"] is True
    assert 0 <= ds.score <= 100


async def test_fluency_penalizes_fillers():
    ev = FluencyEvaluator()
    clean = await ev.evaluate(
        _utt("I went to the market and bought some fruit", start_ms=0, end_ms=3000), CTX
    )
    filled = await ev.evaluate(
        _utt("um uh I like you know went um to the uh market", start_ms=0, end_ms=3000), CTX
    )
    assert filled.scores[0].score < clean.scores[0].score


async def test_fluency_without_timestamps_is_neutral():
    ev = FluencyEvaluator()
    out = await ev.evaluate(_utt("hello there friend"), CTX)
    assert out.scores[0].details["rate_measured"] is False


# --- confidence ------------------------------------------------------------


async def test_confidence_penalizes_hesitation():
    ev = ConfidenceEvaluator()
    steady = await ev.evaluate(_utt("I am confident about this answer", stt_confidence=0.9), CTX)
    shaky = await ev.evaluate(_utt("um uh er I mean uh maybe", stt_confidence=0.5), CTX)
    assert shaky.scores[0].score < steady.scores[0].score


# --- pronunciation (proxy path) --------------------------------------------


async def test_pronunciation_proxy_tracks_confidence():
    ev = PronunciationEvaluator(gop=None)
    hi = await ev.evaluate(_utt("clear speech", stt_confidence=0.95), CTX)
    lo = await ev.evaluate(_utt("mumbled speech", stt_confidence=0.55), CTX)
    assert hi.scores[0].score > lo.scores[0].score
    assert hi.scores[0].details["method"] == "proxy"


async def test_pronunciation_proxy_neutral_without_confidence():
    ev = PronunciationEvaluator(gop=None)
    out = await ev.evaluate(_utt("no confidence available"), CTX)
    assert out.scores[0].score == 60.0


# --- batched LLM evaluator -------------------------------------------------


def _llm_returning(content: str) -> VLLMClient:
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://vllm.test")
    return VLLMClient("http://vllm.test", hot_model="h", cold_model="c", client=http)


_GOOD_JSON = json.dumps(
    {
        "grammar": {
            "score": 80,
            "errors": [{"text": "he go", "correction": "he goes", "type": "agreement"}],
        },
        "vocabulary": {"score": 70, "suggestions": ["utilize"]},
        "listening": {"score": 75},
        "coherence": {"score": 85},
        "relevance": {"score": 90},
        "overall_notes": "solid",
    }
)


async def test_llm_evaluator_parses_five_dimensions():
    ev = LLMEvaluator(_llm_returning(_GOOD_JSON))
    out = await ev.evaluate(_utt("he go to school yesterday"), CTX)
    got = {s.dimension: s.score for s in out.scores}
    assert got == {
        "grammar": 80, "vocabulary": 70, "listening": 75, "coherence": 85, "relevance": 90
    }
    grammar = next(s for s in out.scores if s.dimension == "grammar")
    assert grammar.corrections and grammar.corrections[0]["correction"] == "he goes"


async def test_llm_evaluator_tolerates_surrounding_prose():
    ev = LLMEvaluator(_llm_returning(f"Sure, here you go:\n{_GOOD_JSON}\nHope that helps!"))
    out = await ev.evaluate(_utt("hi"), CTX)
    assert len(out.scores) == 5


async def test_llm_evaluator_bad_json_raises():
    ev = LLMEvaluator(_llm_returning("I could not produce JSON, sorry."))
    with pytest.raises(ValueError, match="no JSON"):
        await ev.evaluate(_utt("hi"), CTX)


def test_extract_json_directly():
    assert _extract_json('prefix {"a": 1} suffix') == {"a": 1}
