"""Tests for the cold-path worker: process/defer/skip, isolation, emit, drain."""

from __future__ import annotations

import asyncio

from backend.coldpath.evaluators.base import DimensionScore, EvaluatorOutput
from backend.coldpath.scoring_service import ScoringService
from backend.coldpath.worker import ColdPathWorker
from backend.core.event_bus import EventBus
from backend.domain.events import AssessmentReady, UtteranceFinalized
from backend.domain.models import Role
from tests.conftest import feed_steady


class FakeEvaluator:
    def __init__(self, name, scores, *, fail=False, available=True):
        self.name = name
        self.version = "v1"
        self._scores = scores
        self._fail = fail
        self._av = available

    def dimensions(self):
        return tuple(self._scores)

    def available(self):
        return self._av

    async def evaluate(self, utt, ctx):
        if self._fail:
            raise RuntimeError("evaluator boom")
        return EvaluatorOutput(
            self.name, "v1", [DimensionScore(d, s) for d, s in self._scores.items()],
            raw=dict(self._scores),
        )


def _prep(users, sessions, utterances):
    users.create("abu_ali", "Abu Ali")
    s = sessions.create("abu_ali")
    u = utterances.add(
        s.session_id, "abu_ali", Role.LEARNER, transcript="hello world", stt_confidence=0.9
    )
    return s, u


def _event(session_id, utterance_id):
    return UtteranceFinalized(
        utterance_id=utterance_id,
        session_id=session_id,
        user_id="abu_ali",
        transcript="hello world",
        stt_confidence=0.9,
        start_ms=None,
        end_ms=None,
        audio_path=None,
    )


def _worker(
    guard, users, sessions, utterances, assessments, evaluator_outputs, evaluators, bus=None
):
    scoring = ScoringService(assessments, evaluator_outputs, users)
    return ColdPathWorker(
        guard=guard,
        evaluators=evaluators,
        scoring=scoring,
        users=users,
        sessions=sessions,
        utterances=utterances,
        assessments=assessments,
        event_bus=bus,
    )


async def test_process_once_creates_assessment(
    guard, sampler, users, sessions, utterances, assessments, evaluator_outputs
):
    feed_steady(guard, sampler, 0.30)  # level 0
    s, u = _prep(users, sessions, utterances)
    w = _worker(guard, users, sessions, utterances, assessments, evaluator_outputs,
                [FakeEvaluator("all", dict.fromkeys(
                    ("pronunciation", "grammar", "vocabulary", "listening",
                     "fluency", "confidence", "coherence", "relevance"), 80.0))])
    status = await w.process_once(_event(s.session_id, u.utterance_id))
    assert status == "processed"
    assert assessments.exists_for_utterance(u.utterance_id)
    assert assessments.count_for_user("abu_ali") == 1


async def test_process_once_is_idempotent(
    guard, sampler, users, sessions, utterances, assessments, evaluator_outputs
):
    feed_steady(guard, sampler, 0.30)
    s, u = _prep(users, sessions, utterances)
    w = _worker(guard, users, sessions, utterances, assessments, evaluator_outputs,
                [FakeEvaluator("f", {"fluency": 70})])
    ev = _event(s.session_id, u.utterance_id)
    assert await w.process_once(ev) == "processed"
    assert await w.process_once(ev) == "skipped"  # already scored
    assert assessments.count_for_user("abu_ali") == 1


async def test_process_once_defers_under_pressure(
    guard, sampler, users, sessions, utterances, assessments, evaluator_outputs
):
    feed_steady(guard, sampler, 0.89)  # level 1 -> cold work paused
    s, u = _prep(users, sessions, utterances)
    w = _worker(guard, users, sessions, utterances, assessments, evaluator_outputs,
                [FakeEvaluator("f", {"fluency": 70})])
    assert await w.process_once(_event(s.session_id, u.utterance_id)) == "deferred"
    assert not assessments.exists_for_utterance(u.utterance_id)


async def test_failed_evaluator_isolated(
    guard, sampler, users, sessions, utterances, assessments, evaluator_outputs
):
    feed_steady(guard, sampler, 0.30)
    s, u = _prep(users, sessions, utterances)
    w = _worker(guard, users, sessions, utterances, assessments, evaluator_outputs,
                [FakeEvaluator("bad", {"grammar": 50}, fail=True),
                 FakeEvaluator("good", {"fluency": 88})])
    assert await w.process_once(_event(s.session_id, u.utterance_id)) == "processed"
    a = assessments.latest_for_user("abu_ali")
    assert a.fluency == 88.0
    assert a.grammar is None  # the failing evaluator contributed nothing


async def test_emits_assessment_ready(
    guard, sampler, users, sessions, utterances, assessments, evaluator_outputs
):
    feed_steady(guard, sampler, 0.30)
    bus = EventBus()
    received = []
    bus.subscribe(AssessmentReady, lambda e: received.append(e) or asyncio.sleep(0))
    s, u = _prep(users, sessions, utterances)
    w = _worker(guard, users, sessions, utterances, assessments, evaluator_outputs,
                [FakeEvaluator("f", {"fluency": 75})], bus=bus)
    await w.process_once(_event(s.session_id, u.utterance_id))
    await bus.drain()
    assert len(received) == 1 and received[0].user_id == "abu_ali"


async def test_background_loop_drains_queue(
    guard, sampler, users, sessions, utterances, assessments, evaluator_outputs
):
    feed_steady(guard, sampler, 0.30)
    bus = EventBus()
    s, u = _prep(users, sessions, utterances)
    w = _worker(guard, users, sessions, utterances, assessments, evaluator_outputs,
                [FakeEvaluator("f", {"fluency": 65})], bus=bus)
    w.attach(bus)
    await w.start()
    try:
        bus.publish(_event(s.session_id, u.utterance_id))
        for _ in range(50):  # up to ~1s
            await asyncio.sleep(0.02)
            if assessments.exists_for_utterance(u.utterance_id):
                break
        assert assessments.exists_for_utterance(u.utterance_id)
    finally:
        await w.stop()
