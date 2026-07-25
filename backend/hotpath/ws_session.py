"""The live WebSocket loop.

Client streams PCM16 mono audio frames; the server segments them with VAD, and on
each finalized utterance runs one hot-path turn, streaming the reply's transcript,
text, and TTS audio chunks back. Control messages: ``{"type":"end"}`` force-ends the
current turn, ``{"type":"bye"}`` closes the session.

Stages are pulled from app state (real models in production, fakes in tests) so the
loop itself is model-agnostic and unit-testable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from starlette.websockets import WebSocket, WebSocketDisconnect

from backend.core.event_bus import EventBus
from backend.core.logging import bind_correlation_id, get_logger
from backend.core.resource_guard import ResourceGuard
from backend.core.util import new_id
from backend.hotpath.base import HotEventKind
from backend.hotpath.pipeline import HotPathPipeline, TurnContext
from backend.hotpath.vad import Segmenter, build_vad
from backend.persistence.db import Database
from backend.persistence.progress import ProgressService
from backend.persistence.repositories import (
    AssessmentRepository,
    SessionRepository,
    UserRepository,
    UtteranceRepository,
)
from config.settings import Settings

log = get_logger("ws_session")


@dataclass
class HotPathStages:
    stt: object
    dialogue: object
    tts: object


async def handle_ws_session(ws: WebSocket, settings: Settings) -> None:
    app = ws.app
    guard: ResourceGuard = app.state.guard
    db: Database = app.state.db
    bus: EventBus = app.state.event_bus
    stages: HotPathStages = app.state.hotpath_stages

    user_id = ws.query_params.get("user_id", "")
    mode = ws.query_params.get("mode", "free")
    correlation_id = new_id("ws")
    bind_correlation_id(correlation_id)

    users = UserRepository(db)
    sessions = SessionRepository(db)
    utterances = UtteranceRepository(db)

    await ws.accept()

    if not users.exists(user_id):
        await ws.send_text(json.dumps({"type": "error", "detail": f"unknown user {user_id!r}"}))
        await ws.close(code=4404)
        return

    session = sessions.create(user_id, mode=mode)  # type: ignore[arg-type]
    pipeline = HotPathPipeline(
        stages.stt,  # type: ignore[arg-type]
        stages.dialogue,  # type: ignore[arg-type]
        stages.tts,  # type: ignore[arg-type]
        guard=guard,
        settings=settings,
        event_bus=bus,
        utterances=utterances,
    )
    segmenter = Segmenter(
        build_vad(settings),
        frame_ms=settings.vad_frame_ms,
        silence_hangover_ms=settings.vad_silence_hangover_ms,
        min_speech_ms=settings.vad_min_speech_ms,
    )
    ctx = TurnContext(session_id=session.session_id, user_id=user_id, history=[])
    frame_bytes = int(settings.hotpath_sample_rate * settings.vad_frame_ms / 1000) * 2
    pending = bytearray()

    await ws.send_text(json.dumps({"type": "session", "session_id": session.session_id}))
    log.info("ws_session_started", session_id=session.session_id, user_id=user_id, mode=mode)

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break

            if (data := msg.get("bytes")) is not None:
                pending.extend(data)
                while len(pending) >= frame_bytes:
                    frame = bytes(pending[:frame_bytes])
                    del pending[:frame_bytes]
                    utt = segmenter.push(frame)
                    if utt:
                        await _run_turn(ws, pipeline, ctx, utt)

            elif (text := msg.get("text")) is not None:
                try:
                    control = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if control.get("type") == "end":
                    utt = segmenter.flush()
                    if utt:
                        await _run_turn(ws, pipeline, ctx, utt)
                elif control.get("type") == "bye":
                    break
    except WebSocketDisconnect:
        pass
    finally:
        sessions.end(session.session_id)
        ProgressService(
            users, sessions, AssessmentRepository(db)
        ).recompute_and_store_streak(user_id)
        log.info("ws_session_ended", session_id=session.session_id)


async def _run_turn(
    ws: WebSocket, pipeline: HotPathPipeline, ctx: TurnContext, pcm: bytes
) -> None:
    transcript = ""
    reply_parts: list[str] = []
    async for ev in pipeline.run_turn(pcm, ctx):
        if ev.kind == HotEventKind.FINAL:
            transcript = ev.text or ""
            await ws.send_text(
                json.dumps({"type": "final", "text": transcript, **ev.meta})
            )
        elif ev.kind == HotEventKind.REPLY:
            # The reply streams a sentence at a time; forward each as a partial.
            reply_parts.append(ev.text or "")
            await ws.send_text(
                json.dumps({"type": "reply", "text": ev.text or "", "partial": True})
            )
        elif ev.kind == HotEventKind.AUDIO and ev.audio is not None:
            await ws.send_bytes(ev.audio)
        elif ev.kind == HotEventKind.TIMINGS and ev.timings is not None:
            await ws.send_text(json.dumps({"type": "turn_end", "timings": ev.timings.as_dict()}))
        elif ev.kind == HotEventKind.ERROR:
            await ws.send_text(json.dumps({"type": "error", "detail": ev.text}))
    # Update rolling conversation context for the next turn.
    reply = " ".join(reply_parts).strip()
    if transcript:
        ctx.history.append({"role": "user", "content": transcript})
    if reply:
        ctx.history.append({"role": "assistant", "content": reply})
