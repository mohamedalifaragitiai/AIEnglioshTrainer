"""Tests for the hot-path pipeline (with fake stages — no real models)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from backend.core.event_bus import EventBus
from backend.domain.events import UtteranceFinalized
from backend.hotpath.base import HotEventKind
from backend.hotpath.pipeline import HotPathPipeline, TurnContext
from tests.conftest import feed_steady


class FakeSTT:
    def __init__(self, text="hello world", conf=0.9, fail=False):
        self.text, self.conf, self.fail = text, conf, fail

    def available(self):
        return True

    async def transcribe(self, pcm, sample_rate):
        if self.fail:
            raise RuntimeError("stt exploded")
        return self.text, self.conf


class FakeDialogue:
    def __init__(self, reply="Nice to meet you."):
        self.reply_text = reply

    async def reply(self, transcript, history):
        return self.reply_text

    async def reply_stream(self, transcript, history, **_):
        yield self.reply_text


class FakeTTS:
    def __init__(self, chunks=3, fail=False):
        self.chunks, self.fail = chunks, fail

    def available(self):
        return True

    async def synthesize_stream(self, text, *, voice=None) -> AsyncIterator[bytes]:
        if self.fail:
            raise RuntimeError("tts exploded")
        for _ in range(self.chunks):
            yield b"\x00\x00" * 160


def _pipeline(guard, settings, **kw):
    return HotPathPipeline(
        kw.pop("stt", FakeSTT()),
        kw.pop("dialogue", FakeDialogue()),
        kw.pop("tts", FakeTTS()),
        guard=guard,
        settings=settings,
        **kw,
    )


async def _collect(pipeline, ctx, pcm=b"\x00\x00" * 1000):
    return [ev async for ev in pipeline.run_turn(pcm, ctx)]


async def test_turn_event_sequence(guard, sampler, settings):
    feed_steady(guard, sampler, 0.30)  # level 0
    events = await _collect(_pipeline(guard, settings), TurnContext("s", "u"))
    kinds = [e.kind for e in events]
    assert kinds[0] == HotEventKind.FINAL
    assert kinds[1] == HotEventKind.REPLY
    assert HotEventKind.AUDIO in kinds
    assert kinds[-1] == HotEventKind.TIMINGS
    assert kinds.count(HotEventKind.AUDIO) == 3


async def test_timings_populated(guard, sampler, settings):
    feed_steady(guard, sampler, 0.30)
    events = await _collect(_pipeline(guard, settings), TurnContext("s", "u"))
    timings = events[-1].timings
    assert timings is not None
    assert timings.first_audio_ms > 0
    assert timings.stt_ms >= 0 and timings.llm_ms >= 0


async def test_final_carries_transcript_and_confidence(guard, sampler, settings):
    feed_steady(guard, sampler, 0.30)
    pipe = _pipeline(guard, settings, stt=FakeSTT(text="how are you", conf=0.77))
    events = await _collect(pipe, TurnContext("s", "u"))
    final = next(e for e in events if e.kind == HotEventKind.FINAL)
    assert final.text == "how are you"
    assert final.meta["confidence"] == 0.77


async def test_hot_path_never_blocked_at_ceiling(guard, sampler, settings):
    feed_steady(guard, sampler, 0.97)  # level 4
    events = await _collect(_pipeline(guard, settings), TurnContext("s", "u"))
    # Live turn still completes; guard degrades (flags) but never blocks/rejects.
    assert events[-1].kind == HotEventKind.TIMINGS
    assert events[-1].timings.degraded is True


async def test_stt_failure_yields_error(guard, sampler, settings):
    feed_steady(guard, sampler, 0.30)
    pipe = _pipeline(guard, settings, stt=FakeSTT(fail=True))
    events = await _collect(pipe, TurnContext("s", "u"))
    assert events[-1].kind == HotEventKind.ERROR
    assert not any(e.kind == HotEventKind.TIMINGS for e in events)


async def test_tts_failure_yields_error(guard, sampler, settings):
    feed_steady(guard, sampler, 0.30)
    pipe = _pipeline(guard, settings, tts=FakeTTS(fail=True))
    events = await _collect(pipe, TurnContext("s", "u"))
    assert events[-1].kind == HotEventKind.ERROR


async def test_emits_utterance_finalized(guard, sampler, settings):
    feed_steady(guard, sampler, 0.30)
    bus = EventBus()
    received = []
    bus.subscribe(UtteranceFinalized, lambda e: received.append(e) or _noop())
    pipe = _pipeline(guard, settings, event_bus=bus)
    await _collect(pipe, TurnContext("sess1", "abu_ali"))
    await bus.drain()
    assert len(received) == 1
    assert received[0].user_id == "abu_ali"
    assert received[0].transcript == "hello world"


async def test_persists_learner_and_coach_utterances(
    guard, sampler, settings, users, sessions, utterances
):
    feed_steady(guard, sampler, 0.30)
    users.create("abu_ali", "Abu Ali")
    s = sessions.create("abu_ali")
    pipe = _pipeline(
        guard, settings, utterances=utterances, stt=FakeSTT(text="good morning")
    )
    await _collect(pipe, TurnContext(s.session_id, "abu_ali"))
    rows = utterances.list_for_session(s.session_id)
    assert len(rows) == 2
    roles = {r.role for r in rows}
    assert {"learner", "coach"} == {str(r) for r in roles}
    learner = next(r for r in rows if str(r.role) == "learner")
    assert learner.transcript == "good morning"


async def _noop():
    return None
