"""The live WebSocket loop.

Client streams PCM16 mono audio frames; the server segments them with VAD, and on
each finalized utterance runs one hot-path turn, streaming the reply's transcript,
text, and TTS audio chunks back. Control messages: ``{"type":"end"}`` force-ends the
current turn, ``{"type":"bye"}`` closes the session.

Every ``end`` gets exactly one closing message — ``turn_end`` when the turn ran, or
``turn_skipped`` when the take was too short to be speech. The client re-enables its
mic on that message, so silence would strand it.

Stages are pulled from app state (real models in production, fakes in tests) so the
loop itself is model-agnostic and unit-testable.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass

from starlette.websockets import WebSocket, WebSocketDisconnect

from backend.auth.service import AuthService
from backend.core.event_bus import EventBus
from backend.core.logging import bind_correlation_id, get_logger
from backend.core.resource_guard import ResourceGuard
from backend.core.util import new_id
from backend.domain.models import User
from backend.hotpath.base import HotEventKind
from backend.hotpath.dialogue import coach_system_prompt
from backend.hotpath.pipeline import HotPathPipeline, TurnContext
from backend.hotpath.vad import Segmenter, build_vad
from backend.persistence.db import Database
from backend.persistence.progress import ProgressService
from backend.persistence.repositories import (
    AssessmentRepository,
    AuthTokenRepository,
    CredentialRepository,
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


async def _authenticate(ws: WebSocket, db: Database, settings: Settings) -> User | None:
    """Consume the opening frame and resolve it to a learner.

    Returns the user, or None after having already sent an error and closed. Close
    codes: 4401 unauthenticated (bad/missing token), 4400 malformed handshake,
    4408 the client connected but never authenticated.

    The wait is bounded: a socket that opens and says nothing would otherwise hold a
    session slot (and a guard-gated model) indefinitely.
    """
    try:
        first = await asyncio.wait_for(ws.receive(), timeout=settings.ws_auth_timeout_s)
    except asyncio.TimeoutError:
        log.info("ws_auth_timeout")
        with contextlib.suppress(Exception):
            await ws.send_text(
                json.dumps({"type": "error", "detail": "timed out waiting for the auth frame"})
            )
            await ws.close(code=4408)
        return None
    except WebSocketDisconnect:
        return None
    if first["type"] == "websocket.disconnect":
        return None

    text = first.get("text")
    if text is None:
        await ws.send_text(
            json.dumps(
                {
                    "type": "error",
                    "detail": 'first message must be {"type":"auth","token":"..."}',
                }
            )
        )
        await ws.close(code=4400)
        return None

    try:
        opening = json.loads(text)
    except json.JSONDecodeError:
        await ws.send_text(json.dumps({"type": "error", "detail": "malformed auth frame"}))
        await ws.close(code=4400)
        return None

    token = opening.get("token") if opening.get("type") == "auth" else None
    if not token:
        await ws.send_text(
            json.dumps({"type": "error", "detail": "authenticate first: send an auth frame"})
        )
        await ws.close(code=4401)
        return None

    auth = AuthService(
        UserRepository(db), CredentialRepository(db), AuthTokenRepository(db), settings
    )
    user = auth.resolve(token)
    if user is None:
        log.info("ws_auth_failed")
        await ws.send_text(
            json.dumps({"type": "error", "detail": "token is invalid, expired or revoked"})
        )
        await ws.close(code=4401)
        return None
    return user


async def handle_ws_session(ws: WebSocket, settings: Settings) -> None:
    app = ws.app
    guard: ResourceGuard = app.state.guard
    db: Database = app.state.db
    bus: EventBus = app.state.event_bus
    stages: HotPathStages = app.state.hotpath_stages

    mode = ws.query_params.get("mode", "free")
    topic = ws.query_params.get("topic") or None
    # Push-to-talk: the client (a Speak button) decides when the turn ends, so we do
    # NOT auto-segment on silence — the whole recording is one turn, flushed on 'end'.
    ptt = ws.query_params.get("ptt", "").lower() in ("1", "true", "yes")
    correlation_id = new_id("ws")
    bind_correlation_id(correlation_id)

    users = UserRepository(db)
    sessions = SessionRepository(db)
    utterances = UtteranceRepository(db)

    await ws.accept()

    # Authenticate FIRST, and take the identity from the token — never from a query
    # parameter. The client's opening frame must be {"type":"auth","token":...}; a
    # token in the URL would end up in access logs and proxy history.
    authed = await _authenticate(ws, db, settings)
    if authed is None:
        return
    user, user_id = authed, authed.user_id

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
    # Build a coach persona pitched at the learner's level + the chosen topic, so
    # generated questions match their level and the topic they want to practice.
    level = user.current_level
    ctx = TurnContext(
        session_id=session.session_id,
        user_id=user_id,
        history=[],
        system_prompt=coach_system_prompt(level, topic),
    )
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
                if ptt:
                    continue  # accumulate the whole take; the button ends the turn
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
                    if ptt:
                        # Whole recording is the utterance; require a minimum length.
                        min_bytes = (
                            settings.hotpath_sample_rate * 2 * settings.vad_min_speech_ms // 1000
                        )
                        utt = bytes(pending) if len(pending) >= min_bytes else None
                        pending.clear()
                    else:
                        utt = segmenter.flush()
                    if utt:
                        await _run_turn(ws, pipeline, ctx, utt)
                    else:
                        # Too short to be speech. ALWAYS answer an 'end' — the client
                        # blocks its mic until the turn closes, so staying silent here
                        # would strand it (and would hang any test draining the turn).
                        await ws.send_text(
                            json.dumps(
                                {
                                    "type": "turn_skipped",
                                    "detail": (
                                        "that was too short to score — hold the button and "
                                        f"speak for at least "
                                        f"{settings.vad_min_speech_ms / 1000:.1f}s"
                                    ),
                                }
                            )
                        )
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
