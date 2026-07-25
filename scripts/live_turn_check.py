"""End-to-end live-turn check against the RUNNING app.

Synthesizes a learner utterance with Kokoro (CPU), streams it as 16kHz PCM into the
live /ws/session WebSocket, and confirms the full hot path: real STT transcript ->
real vLLM reply -> real TTS audio back. Proves audio -> transcript -> reply -> speech
through the actual running server (models loaded, LLM via vLLM).

Run:  ./.venv/Scripts/python.exe scripts/live_turn_check.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import wave
from pathlib import Path

import numpy as np
import websockets

# Model replies can contain emoji; make the Windows console tolerate them.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

USER = "abu_ali"
WS = f"ws://127.0.0.1:8000/ws/session?user_id={USER}&mode=free&ptt=1"
SAY = "Hello coach. I want to practice my English speaking today. Can you ask me a question?"


def synth_learner_16k() -> bytes:
    """Generate speech with Kokoro (CPU) and resample 24k -> 16k PCM16."""
    from kokoro import KPipeline

    pipe = KPipeline(lang_code="a", device="cpu")
    parts = []
    for _gs, _ps, audio in pipe(SAY, voice="af_heart"):
        a = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
        parts.append(a.astype(np.float32))
    audio24 = np.concatenate(parts)
    n_out = int(len(audio24) * 16000 / 24000)
    audio16 = np.interp(
        np.arange(n_out) * 24000 / 16000, np.arange(len(audio24)), audio24
    ).astype(np.float32)
    print(f"[gen] synthesized {len(audio24) / 24000:.1f}s of learner speech "
          f"-> {n_out} samples @16k")
    return (np.clip(audio16, -1, 1) * 32767).astype(np.int16).tobytes()


async def main() -> int:
    pcm = synth_learner_16k()

    async with websockets.connect(WS, max_size=None) as ws:
        hello = json.loads(await ws.recv())
        print(f"[ws] session started: {hello.get('session_id', '?')[:24]}")

        # Stream the utterance (server re-chunks into VAD frames), then end the turn.
        block = 3200  # 100ms @16k
        for i in range(0, len(pcm), block):
            await ws.send(pcm[i : i + block])
        await ws.send(json.dumps({"type": "end"}))
        print(f"[ws] streamed {len(pcm)} bytes, sent end-of-turn; waiting for reply...")

        transcript = reply = None
        timings = None
        reply_audio = bytearray()
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=60)
            if isinstance(msg, bytes | bytearray):
                reply_audio += msg
                continue
            j = json.loads(msg)
            if j["type"] == "final":
                transcript = j["text"]
                print(f"[STT]   transcript : {transcript!r}  (conf {j.get('confidence')})")
            elif j["type"] == "reply":
                reply = j["text"]
                print(f"[LLM]   reply      : {reply!r}")
            elif j["type"] == "turn_end":
                timings = j["timings"]
                break
            elif j["type"] == "error":
                print(f"[ERROR] {j.get('detail')}")
                return 1
        await ws.send(json.dumps({"type": "bye"}))

    out = Path("data/live_turn_reply.wav")
    out.parent.mkdir(exist_ok=True)
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)  # Kokoro rate
        wf.writeframes(bytes(reply_audio))

    print(f"[TTS]   reply audio : {len(reply_audio)} bytes "
          f"({len(reply_audio) / 2 / 24000:.1f}s) -> {out}")
    print(f"[time]  {timings}")
    ok = bool(transcript and reply and reply_audio)
    print("\n" + ("PASS: audio -> transcript -> reply -> speech, end to end."
                  if ok else "INCOMPLETE: one stage produced nothing (see above)."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
