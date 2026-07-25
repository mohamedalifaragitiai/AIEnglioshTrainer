"""Tests for cold-path score aggregation + persistence."""

from __future__ import annotations

import json

import pytest

from backend.coldpath.evaluators.base import DimensionScore, EvaluatorOutput, UtteranceForEval
from backend.coldpath.scoring import DIMENSIONS, compute_overall
from backend.coldpath.scoring_service import ScoringService
from backend.domain.models import Role


def _prep_utt(users, sessions, utterances):
    """Create the user/session/utterance chain so FKs (evaluator_outputs,
    assessments -> utterances) are satisfied, then return an eval view of it."""
    users.create("abu_ali", "Abu Ali")
    s = sessions.create("abu_ali")
    u = utterances.add(s.session_id, "abu_ali", Role.LEARNER, transcript="hello")
    return UtteranceForEval(
        utterance_id=u.utterance_id, session_id=s.session_id, user_id="abu_ali", transcript="hello"
    )


def _output(evaluator, scores: dict[str, float]) -> EvaluatorOutput:
    return EvaluatorOutput(
        evaluator,
        "v1",
        [DimensionScore(d, s) for d, s in scores.items()],
        raw={"scores": scores},
    )


def _service(assessments, evaluator_outputs, users) -> ScoringService:
    return ScoringService(assessments, evaluator_outputs, users)


def test_full_dimensions_match_weighted_formula(
    users, sessions, utterances, assessments, evaluator_outputs
):
    utt = _prep_utt(users, sessions, utterances)
    scores = dict.fromkeys(DIMENSIONS, 80.0)
    svc = _service(assessments, evaluator_outputs, users)
    a = svc.record(utt, [_output("all", scores)])
    assert a.overall == pytest.approx(compute_overall(scores))  # weights sum to 1
    assert a.overall == pytest.approx(80.0)
    # stored, level advanced (80 -> level 3), and raw output persisted.
    assert assessments.count_for_user("abu_ali") == 1
    assert users.get("abu_ali").current_level == 3
    outs = evaluator_outputs.list_for_utterance(utt.utterance_id)
    assert len(outs) == 1
    assert json.loads(outs[0].payload_json)["scores"]["grammar"] == 80.0


def test_partial_dimensions_renormalized(
    users, sessions, utterances, assessments, evaluator_outputs
):
    utt = _prep_utt(users, sessions, utterances)
    svc = _service(assessments, evaluator_outputs, users)
    # Only fluency + confidence present (LLM evaluator skipped) — both 90.
    a = svc.record(utt, [_output("fluency", {"fluency": 90.0, "confidence": 90.0})])
    # Renormalized over present dims => 90, not dragged toward 0 by the missing six.
    assert a.overall == pytest.approx(90.0)
    assert a.fluency == 90.0
    assert a.grammar is None  # genuinely absent, not zero


def test_multiple_evaluators_merge_dimensions(
    users, sessions, utterances, assessments, evaluator_outputs
):
    utt = _prep_utt(users, sessions, utterances)
    svc = _service(assessments, evaluator_outputs, users)
    outputs = [
        _output("llm", {"grammar": 60, "vocabulary": 60, "listening": 60,
                        "coherence": 60, "relevance": 60}),
        _output("fluency", {"fluency": 100}),
        _output("confidence", {"confidence": 100}),
        _output("pron", {"pronunciation": 100}),
    ]
    a = svc.record(utt, outputs)
    # All 8 present; four raw outputs -> stored separately.
    assert len(evaluator_outputs.list_for_utterance(utt.utterance_id)) == 4
    assert a.grammar == 60 and a.fluency == 100 and a.pronunciation == 100
