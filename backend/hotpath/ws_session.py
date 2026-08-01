"""The live WebSocket loop.

Client streams PCM16 mono audio frames; the server segments them with VAD, and on
each finalized utterance runs one hot-path turn, streaming the reply's transcript,
text, and TTS audio chunks back. Control messages: ``{"type":"end"}`` force-ends the
current turn, ``{"type":"bye"}`` closes the session.

Every ``end`` gets exactly one closing message — ``turn_end`` when the turn ran, or
``turn_skipped`` when the take was too short to be speech. The client re-enables its
mic on that message, so silence would strand it.

A reader task drains the socket concurrently with a running turn, so ``bye`` and
disconnects register mid-reply rather than only between turns; the turn then unwinds
at its next event instead of synthesizing speech for a client that has already left.

Stages are pulled from app state (real models in production, fakes in tests) so the
loop itself is model-agnostic and unit-testable.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass

from starlette.websockets import WebSocket, WebSocketDisconnect

from backend.api.deps import resolve_token
from backend.core.event_bus import EventBus
from backend.core.logging import bind_correlation_id, get_logger
from backend.core.resource_guard import ResourceGuard
from backend.core.util import new_id
from backend.hotpath.base import HotEventKind
from backend.hotpath.dialogue import coach_system_prompt
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

    # A browser cannot set headers on a WebSocket handshake, so the token rides
    # in the query string (same-origin clients may lean on the cookie instead).
    # The token wins over ?user_id= — otherwise the parameter alone would still
    # be enough to practise as someone else.
    if settings.auth_required:
        token = ws.query_params.get("token") or ws.cookies.get(settings.auth_cookie_name)
        authenticated = resolve_token(db, token)
        if authenticated is None:
            await ws.send_text(
                json.dumps({"type": "error", "detail": "authentication required"})
            )
            await ws.close(code=4401)
            return
        if user_id and user_id != authenticated:
            await ws.send_text(json.dumps({"type": "error", "detail": "not your profile"}))
            await ws.close(code=4403)
            return
        user_id = authenticated

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
    # Build a coach persona pitched at the learner's level + the chosen topic, so
    # generated questions match their level and the topic they want to practice.
    user = users.get(user_id)
    level = user.current_level if user else 0
    ctx = TurnContext(
        session_id=session.session_id,
        user_id=user_id,
        history=[],
        system_prompt=coach_system_prompt(level, topic),
        # Reading practice streams audio for the transcript alone: the learner is
        # reading a fixed passage, so a coach reply is noise in their history and
        # an LLM+TTS run this box does not need to spend.
        reply=ws.query_params.get("reply", "1").lower() not in ("0", "false", "no"),
    )
    frame_bytes = int(settings.hotpath_sample_rate * settings.vad_frame_ms / 1000) * 2
    pending = bytearray()

    await ws.send_text(json.dumps({"type": "session", "session_id": session.session_id}))
    log.info("ws_session_started", session_id=session.session_id, user_id=user_id, mode=mode)

    # A dedicated reader drains the socket even while a turn is streaming, so a
    # 'bye' or a disconnect is noticed immediately instead of only between turns.
    # Awaiting receive() inline meant a learner who ended the session mid-reply
    # left the server generating LLM + TTS for a client that had already gone.
    # Ordering is preserved: everything still reaches the loop through the queue.
    inbox: asyncio.Queue[dict] = asyncio.Queue()
    stop = asyncio.Event()

    async def _reader() -> None:
        try:
            while True:
                m = await ws.receive()
                if m["type"] == "websocket.disconnect" or _is_bye(m):
                    stop.set()
                await inbox.put(m)
                if stop.is_set():
                    return
        except (WebSocketDisconnect, RuntimeError):
            # RuntimeError: receive() called once the socket is already gone.
            stop.set()
            await inbox.put({"type": "websocket.disconnect"})

    reader = asyncio.create_task(_reader())

    try:
        while True:
            msg = await inbox.get()
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
                        # Log the size that arrived. When a turn produces nothing
                        # the first question is whether any audio reached the
                        # server at all, and without this the answer was
                        # unknowable from the logs.
                        log.info(
                            "ws_turn_start",
                            session_id=session.session_id,
                            mode=mode,
                            reply=ctx.reply,
                            audio_bytes=len(utt),
                            audio_seconds=round(len(utt) / (settings.hotpath_sample_rate * 2), 2),
                        )
                        await _run_turn(ws, pipeline, ctx, utt, stop)
                        log.info("ws_turn_done", session_id=session.session_id)

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
                        # Log the size that arrived. When a turn produces nothing
                        # the first question is whether any audio reached the
                        # server at all, and without this the answer was
                        # unknowable from the logs.
                        log.info(
                            "ws_turn_start",
                            session_id=session.session_id,
                            mode=mode,
                            reply=ctx.reply,
                            audio_bytes=len(utt),
                            audio_seconds=round(len(utt) / (settings.hotpath_sample_rate * 2), 2),
                        )
                        await _run_turn(ws, pipeline, ctx, utt, stop)
                        log.info("ws_turn_done", session_id=session.session_id)
                    else:
                        log.info(
                            "ws_turn_skipped_short",
                            session_id=session.session_id,
                            buffered_bytes=len(pending),
                        )
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
        reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reader
        sessions.end(session.session_id)
        ProgressService(
            users, sessions, AssessmentRepository(db)
        ).recompute_and_store_streak(user_id)
        log.info("ws_session_ended", session_id=session.session_id)


def _is_bye(msg: dict) -> bool:
    """True for a ``{"type": "bye"}`` control frame, ignoring anything unparseable."""
    if (text := msg.get("text")) is None:
        return False
    try:
        return json.loads(text).get("type") == "bye"
    except (json.JSONDecodeError, AttributeError):
        return False


async def _run_turn(
    ws: WebSocket,
    pipeline: HotPathPipeline,
    ctx: TurnContext,
    pcm: bytes,
    stop: asyncio.Event | None = None,
) -> None:
    transcript = ""
    reply_parts: list[str] = []
    # aclosing() so an early break shuts the pipeline's generator down promptly
    # instead of leaving it for the GC to finalize.
    async with contextlib.aclosing(pipeline.run_turn(pcm, ctx)) as stream:
        async for ev in stream:
            # The learner ended the session (or vanished) mid-reply — stop burning
            # GPU on speech nobody is listening to. Checked between events, so the
            # turn unwinds at the next sentence or audio chunk.
            if stop is not None and stop.is_set():
                break
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
                await ws.send_text(
                    json.dumps({"type": "turn_end", "timings": ev.timings.as_dict()})
                )
            elif ev.kind == HotEventKind.ERROR:
                await ws.send_text(json.dumps({"type": "error", "detail": ev.text}))
    # Update rolling conversation context for the next turn.
    reply = " ".join(reply_parts).strip()
    if transcript:
        ctx.history.append({"role": "user", "content": transcript})
    if reply:
        ctx.history.append({"role": "assistant", "content": reply})
