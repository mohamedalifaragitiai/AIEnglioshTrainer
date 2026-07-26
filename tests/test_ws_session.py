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


def test_ws_turn_flows_to_cold_path_assessment():
    """A live turn emits UtteranceFinalized -> the cold-path worker scores it ->
    an assessment is stored (deterministic evaluators run even without the LLM)."""
    import time

    with TestClient(app) as client:
        uid = "ws" + new_id()[:8]
        client.post("/users", json={"user_id": uid, "display_name": "WS"})
        client.app.state.hotpath_stages = HotPathStages(FakeSTT(), FakeDialogue(), FakeTTS())

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
