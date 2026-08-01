"""End-to-end READING check against the RUNNING app.

Fetches a passage, speaks it with Kokoro, streams it into ``/ws/session`` exactly
as the browser does (``mode=reading&ptt=1&reply=0``), waits for the transcript,
then scores the attempt through the API.

This exists because a reading attempt that produces nothing gives the same
symptom — a UI waiting forever — whether the microphone never captured, the
socket dropped, the transcript never came back, or scoring failed. Running the
same path without a browser says which half is at fault.

Run:  ./.venv/Scripts/python.exe scripts/live_reading_check.py
      ./.venv/Scripts/python.exe scripts/live_reading_check.py --user abu_ali
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import websockets

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

BASE = "http://127.0.0.1:8000"


def api(path: str, token: str | None = None, data: dict | None = None) -> dict:
    req = urllib.request.Request(
        BASE + path,
        method="POST" if data is not None else "GET",
        data=json.dumps(data).encode() if data is not None else None,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode()
    return json.loads(body) if body.strip() else {}


def speak_16k(text: str) -> bytes:
    """Kokoro (CPU) -> 16kHz PCM16, the format the socket expects."""
    from kokoro import KPipeline

    pipe = KPipeline(lang_code="a", device="cpu")
    parts = []
    for _gs, _ps, audio in pipe(text, voice="af_heart"):
        a = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
        parts.append(a.astype(np.float32))
    audio24 = np.concatenate(parts)
    n_out = int(len(audio24) * 16000 / 24000)
    audio16 = np.interp(
        np.arange(n_out) * 24000 / 16000, np.arange(len(audio24)), audio24
    ).astype(np.float32)
    print(f"[gen]  spoke the passage: {len(audio24) / 24000:.1f}s -> {n_out} samples @16k")
    return (np.clip(audio16, -1, 1) * 32767).astype(np.int16).tobytes()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="abu_ali")
    ap.add_argument("--password", help="only needed when COACH_AUTH_REQUIRED is on")
    ap.add_argument("--level", type=int, default=1)
    args = ap.parse_args()

    token = None
    status = api("/auth/status")
    if status.get("auth_required"):
        password = args.password
        if not password:
            pw_file = Path("M:/AIEnglioshTrainer/admin-password.txt")
            if pw_file.exists():
                for line in pw_file.read_text(encoding="utf-8").splitlines():
                    if line.strip().startswith("password:"):
                        password = line.split("password:", 1)[1].strip()
        if not password:
            print("auth is enforced — pass --password")
            return 2
        token = api("/auth/login", data={"user_id": args.user, "password": password})["token"]
        print(f"[auth] signed in as {args.user}")

    passage = api(f"/reading/passage?level={args.level}", token)
    print(f"[read] passage {passage['title']!r} ({passage['words']} words)")
    pcm = speak_16k(passage["text"])

    ws_url = (
        f"ws://127.0.0.1:8000/ws/session?user_id={args.user}"
        f"&mode=reading&ptt=1&reply=0" + (f"&token={token}" if token else "")
    )
    transcript = None
    async with websockets.connect(ws_url, max_size=None) as ws:
        hello = json.loads(await ws.recv())
        print(f"[ws]   session {hello.get('session_id', '?')[:24]}")
        block = 3200  # 100ms @16k, same chunking the browser produces
        for i in range(0, len(pcm), block):
            await ws.send(pcm[i : i + block])
        await ws.send(json.dumps({"type": "end"}))
        print(f"[ws]   streamed {len(pcm)} bytes ({len(pcm) / 32000:.1f}s), sent end")

        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=90)
            except TimeoutError:
                print("[FAIL] no transcript within 90s — the turn never completed")
                return 1
            if isinstance(msg, bytes | bytearray):
                print("[warn] audio came back; reply=0 should have suppressed it")
                continue
            j = json.loads(msg)
            if j["type"] == "final":
                transcript = j["text"]
                print(f"[STT]  transcript: {transcript!r}")
            elif j["type"] == "turn_end":
                print(f"[time] {j.get('timings')}")
                break
            elif j["type"] == "turn_skipped":
                print("[FAIL] the server judged the take too short to be speech")
                return 1
            elif j["type"] == "error":
                print(f"[FAIL] {j.get('detail')}")
                return 1
        await ws.send(json.dumps({"type": "bye"}))

    result = api(
        f"/users/{args.user}/reading/score",
        token,
        {
            "reference": passage["text"],
            "spoken": transcript or "",
            "duration_s": len(pcm) / 32000,
            "level": passage["level"],
            "title": passage["title"],
        },
    )
    print(
        f"[score] accuracy {result['accuracy']}%  wpm {result['wpm']}  pace {result['pace']}  "
        f"stored={bool(result.get('attempt_id'))}"
    )
    print(f"[score] {result['verdict']}")

    ok = bool(transcript) and result.get("attempt_id")
    print("\n" + ("PASS: audio -> transcript -> score -> stored." if ok else "FAIL: see above."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
