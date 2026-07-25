"""End-to-end WebSocket hot-path test with fake stages (no real models)."""

from __future__ import annotations

import json
from array import array
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from backend.core.util import new_id
from backend.hotpath.ws_session import HotPathStages
from backend.main import app

SR = 16000
FRAME_SAMPLES = SR * 20 // 1000  # 320


def _loud() -> bytes:
    return array("h", [9000] * FRAME_SAMPLES).tobytes()


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
    """Collect server messages until turn_end/error. Returns (json_msgs, audio_count)."""
    msgs, audio = [], 0
    while True:
        m = ws.receive()
        if m.get("text") is not None:
            j = json.loads(m["text"])
            msgs.append(j)
            if j["type"] in ("turn_end", "error"):
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

            # 12 speech frames (> min_speech) then force end-of-turn.
            for _ in range(12):
                ws.send_bytes(_loud())
            ws.send_text(json.dumps({"type": "end"}))

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
            for _ in range(12):
                ws.send_bytes(_loud())
            ws.send_text(json.dumps({"type": "end"}))
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
            for _ in range(12):
                ws.send_bytes(_loud())
            ws.send_text(json.dumps({"type": "end"}))
            _drain_turn(ws)
            ws.send_text(json.dumps({"type": "bye"}))

        # A session and the learner+coach utterances were persisted.
        sessions = client.get(f"/users/{uid}/sessions").json()
        assert len(sessions) == 1
        utts = client.get(f"/sessions/{sessions[0]['session_id']}/utterances").json()
        assert len(utts) == 2
