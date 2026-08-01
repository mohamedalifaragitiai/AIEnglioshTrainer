"""End-to-end WebSocket hot-path test with fake stages (no real models)."""

from __future__ import annotations

import json
import threading
from array import array
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from backend.core.util import new_id
from backend.hotpath.ws_session import HotPathStages
from backend.main import app
from config.settings import get_settings

_S = get_settings()
SR = _S.hotpath_sample_rate
FRAME_SAMPLES = SR * _S.vad_frame_ms // 1000
# Derive the take length from the VAD threshold instead of hardcoding a frame count:
# a hardcoded 12 silently became too short when vad_min_speech_ms moved to 300, and
# the segmenter then finalized nothing — so the server sent nothing and the test hung.
SPEECH_FRAMES = _S.vad_min_speech_ms // _S.vad_frame_ms + 3


def _loud() -> bytes:
    return array("h", [9000] * FRAME_SAMPLES).tobytes()


def _receive_within(ws, timeout: float = 15.0) -> dict:
    """``ws.receive()`` with a deadline.

    TestClient's receive blocks forever, so any server that stops talking mid-turn
    would hang the whole suite instead of failing one test. Fail loudly instead.
    """
    box: list = []
    t = threading.Thread(target=lambda: box.append(ws.receive()), daemon=True)
    t.start()
    t.join(timeout)
    if not box:
        raise AssertionError(
            f"no server message within {timeout}s — the turn never ran and the server "
            f"never closed it out (every 'end' must answer with turn_end or turn_skipped)"
        )
    return box[0]


def _speak_a_turn(ws) -> None:
    """Send a take long enough to clear the VAD threshold, then force end-of-turn."""
    for _ in range(SPEECH_FRAMES):
        ws.send_bytes(_loud())
    ws.send_text(json.dumps({"type": "end"}))


class FakeSTT:
    def available(self):
        return True

    async def transcribe(self, pcm, sample_rate):
        return "hello coach", 0.95


class FakeDialogue:
    async def reply(self, transcript, history):
        return "Hello! How can I help you practice today?"

    async def reply_stream(self, transcript, history, **_):
        yield "Hello! How can I help you practice today?"


class FakeTTS:
    def available(self):
        return True

    async def synthesize_stream(self, text) -> AsyncIterator[bytes]:
        for _ in range(3):
            yield b"\x00\x00" * 160


def _drain_turn(ws):
    """Collect server messages until the turn closes. Returns (json_msgs, audio_count)."""
    msgs, audio = [], 0
    while True:
        m = _receive_within(ws)
        if m.get("text") is not None:
            j = json.loads(m["text"])
            msgs.append(j)
            if j["type"] in ("turn_end", "turn_skipped", "error"):
                return msgs, audio
        elif m.get("bytes") is not None:
            audio += 1


def test_ws_turn_streams_transcript_reply_audio_timings():
    with TestClient(app) as client:
        uid = "ws" + new_id()[:8]
        client.post("/users", json={"user_id": uid, "display_name": "WS"})
        # Inject fake stages after lifespan built the real (model-less) ones.
        client.app.state.hotpath_stages = HotPathStages(FakeSTT(), FakeDialogue(), FakeTTS())

        with client.websocket_connect(f"/ws/session?user_id={uid}&mode=free") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "session"

            _speak_a_turn(ws)
            msgs, audio = _drain_turn(ws)
            types = [m["type"] for m in msgs]
            assert "final" in types and "reply" in types and "turn_end" in types
            assert audio == 3
            final = next(m for m in msgs if m["type"] == "final")
            assert final["text"] == "hello coach"
            reply = next(m for m in msgs if m["type"] == "reply")
            assert "help you practice" in reply["text"]
            timings = next(m for m in msgs if m["type"] == "turn_end")["timings"]
            assert timings["first_audio_ms"] >= 0

            ws.send_text(json.dumps({"type": "bye"}))


class SlowTTS:
    """Streams a long reply slowly, so a 'bye' can land while the turn is still
    in flight. Counts what it actually produced."""

    TOTAL = 60
    chunks = 0

    def available(self):
        return True

    async def synthesize_stream(self, text) -> AsyncIterator[bytes]:
        import asyncio

        for _ in range(self.TOTAL):
            SlowTTS.chunks += 1
            await asyncio.sleep(0.01)
            yield b"\x00\x00" * 160


def test_ws_bye_aborts_an_in_flight_turn():
    """'bye' must be noticed *during* a reply, not only between turns.

    receive() used to be awaited inline in the loop, so while a turn streamed
    nobody was reading the socket: a learner who pressed End mid-reply left the
    server generating LLM + TTS for a client that had already gone. A reader task
    now drains the socket concurrently and trips a stop event the turn honours.
    """
    import time

    SlowTTS.chunks = 0
    with TestClient(app) as client:
        uid = "ws" + new_id()[:8]
        client.post("/users", json={"user_id": uid, "display_name": "WS"})
        client.app.state.hotpath_stages = HotPathStages(FakeSTT(), FakeDialogue(), SlowTTS())

        with client.websocket_connect(f"/ws/session?user_id={uid}&mode=free&ptt=1") as ws:
            ws.receive_json()  # session
            _speak_a_turn(ws)
            # Wait until audio is genuinely flowing, so 'bye' truly arrives mid-turn.
            while _receive_within(ws).get("bytes") is None:
                pass
            ws.send_text(json.dumps({"type": "bye"}))
            # Sample while the socket is STILL OPEN, and after comfortably longer
            # than the whole reply would take (60 * 10ms). Closing the socket first
            # would abort the turn on a failed send and make this pass even with the
            # stop check removed — it has to be the 'bye' that stops it, not the close.
            time.sleep(1.5)
            observed = SlowTTS.chunks

    assert observed < SlowTTS.TOTAL, (
        f"TTS produced all {observed}/{SlowTTS.TOTAL} chunks with the socket still "
        f"open — the turn ignored 'bye' and ran to completion for a client that had "
        f"already left"
    )


def test_ws_turn_flows_to_cold_path_assessment():
    """A live turn emits UtteranceFinalized -> the cold-path worker scores it ->
    an assessment is stored (deterministic evaluators run even without the LLM).

    The guard is pinned to an idle machine for the duration. This test asserts
    what the cold path does when it is *allowed to run*; left on the real
    sampler it also asserts that the developer's machine happens to be quiet,
    and fails on a box sitting above ladder_l1 for reasons that have nothing to
    do with the code — the guard defers the job, re-queues it with backoff for
    up to coldpath_max_defer_s (60s), and the 2.5s poll below gives up first.
    """
    import time

    from tests.conftest import FakeSampler

    with TestClient(app) as client:
        uid = "ws" + new_id()[:8]
        client.post("/users", json={"user_id": uid, "display_name": "WS"})
        client.app.state.hotpath_stages = HotPathStages(FakeSTT(), FakeDialogue(), FakeTTS())

        # Swap the sampler, not just the level: the guard's background loop keeps
        # sampling every second and would put a real reading straight back.
        guard = client.app.state.guard
        guard._sampler = FakeSampler()
        guard._window.clear()
        for _ in range(guard._window.maxlen or 3):
            guard.feed(guard._sampler.sample())
        assert guard.degradation_level == 0, "the guard must be idle or this proves nothing"

        with client.websocket_connect(f"/ws/session?user_id={uid}") as ws:
            ws.receive_json()  # session
            _speak_a_turn(ws)
            _drain_turn(ws)
            ws.send_text(json.dumps({"type": "bye"}))

        # Cold path runs on the app loop; poll until the assessment lands.
        assessments = []
        for _ in range(50):
            assessments = client.get(f"/users/{uid}/assessments").json()
            if assessments:
                break
            time.sleep(0.05)
        assert len(assessments) == 1
        a = assessments[0]
        # Deterministic evaluators contributed; LLM dims absent (no vLLM in tests).
        assert a["fluency"] is not None
        assert a["pronunciation"] is not None
        assert a["overall"] is not None


def test_ws_short_take_is_closed_out_not_ignored():
    """A take below vad_min_speech_ms finalizes no utterance. The server must still
    close the turn — the client keeps its mic disabled until it hears back, so silence
    here strands the UI (and hangs anything draining the turn)."""
    with TestClient(app) as client:
        uid = "ws" + new_id()[:8]
        client.post("/users", json={"user_id": uid, "display_name": "WS"})
        client.app.state.hotpath_stages = HotPathStages(FakeSTT(), FakeDialogue(), FakeTTS())

        with client.websocket_connect(f"/ws/session?user_id={uid}") as ws:
            ws.receive_json()  # session
            for _ in range(max(1, SPEECH_FRAMES // 4)):  # deliberately too short
                ws.send_bytes(_loud())
            ws.send_text(json.dumps({"type": "end"}))

            msgs, audio = _drain_turn(ws)
            assert [m["type"] for m in msgs] == ["turn_skipped"]
            assert audio == 0
            assert msgs[0]["detail"]
            ws.send_text(json.dumps({"type": "bye"}))


def test_ws_short_take_is_closed_out_in_ptt_mode():
    """Same guarantee on the push-to-talk path the UI actually uses (ptt=1)."""
    with TestClient(app) as client:
        uid = "ws" + new_id()[:8]
        client.post("/users", json={"user_id": uid, "display_name": "WS"})
        client.app.state.hotpath_stages = HotPathStages(FakeSTT(), FakeDialogue(), FakeTTS())

        with client.websocket_connect(f"/ws/session?user_id={uid}&ptt=1") as ws:
            ws.receive_json()  # session
            ws.send_bytes(_loud())  # one frame — far below the threshold
            ws.send_text(json.dumps({"type": "end"}))

            msgs, _ = _drain_turn(ws)
            assert [m["type"] for m in msgs] == ["turn_skipped"]

            # And a long enough take on the same session still runs a full turn.
            for _ in range(SPEECH_FRAMES):
                ws.send_bytes(_loud())
            ws.send_text(json.dumps({"type": "end"}))
            msgs, audio = _drain_turn(ws)
            types = [m["type"] for m in msgs]
            assert "final" in types and "turn_end" in types and audio == 3
            ws.send_text(json.dumps({"type": "bye"}))


def test_ws_rejects_unknown_user():
    with TestClient(app) as client:
        client.app.state.hotpath_stages = HotPathStages(FakeSTT(), FakeDialogue(), FakeTTS())
        with client.websocket_connect("/ws/session?user_id=ghost") as ws:
            m = ws.receive_json()
            assert m["type"] == "error"


def test_ws_persists_session_and_utterances():
    with TestClient(app) as client:
        uid = "ws" + new_id()[:8]
        client.post("/users", json={"user_id": uid, "display_name": "WS"})
        client.app.state.hotpath_stages = HotPathStages(FakeSTT(), FakeDialogue(), FakeTTS())

        with client.websocket_connect(f"/ws/session?user_id={uid}") as ws:
            ws.receive_json()  # session
            _speak_a_turn(ws)
            _drain_turn(ws)
            ws.send_text(json.dumps({"type": "bye"}))

        # A session and the learner+coach utterances were persisted.
        sessions = client.get(f"/users/{uid}/sessions").json()
        assert len(sessions) == 1
        utts = client.get(f"/sessions/{sessions[0]['session_id']}/utterances").json()
        assert len(utts) == 2


def test_reading_mode_returns_a_transcript_without_a_coach_reply():
    """Reading practice wants the words back, not a conversation: no LLM, no TTS,
    and no blank coach bubble in the learner's history."""
    with TestClient(app) as client:
        uid = "rd" + new_id()[:8]
        client.post("/users", json={"user_id": uid, "display_name": "Reader"})
        client.app.state.hotpath_stages = HotPathStages(FakeSTT(), FakeDialogue(), FakeTTS())

        # mode=reading included deliberately: the first version of this test
        # omitted it, so a mode the SessionMode enum did not accept passed
        # here and crashed the socket in the browser.
        url = f"/ws/session?user_id={uid}&mode=reading&ptt=1&reply=0"
        with client.websocket_connect(url) as ws:
            ws.receive_json()  # session
            _speak_a_turn(ws)
            kinds = []
            for _ in range(6):
                msg = _receive_within(ws)
                kinds.append(json.loads(msg["text"])["type"] if "text" in msg else "bytes")
                if kinds[-1] == "turn_end":
                    break
            ws.send_text(json.dumps({"type": "bye"}))

        assert "final" in kinds, kinds
        assert "turn_end" in kinds, "every 'end' must still be closed out"
        assert "reply" not in kinds, "reading mode must not generate a coach reply"

        sessions = client.get(f"/users/{uid}/sessions").json()
        turns = client.get(f"/sessions/{sessions[0]['session_id']}/utterances").json()
        assert [t["role"] for t in turns] == ["learner"], turns
