"""Turn the app's log into a readable feed of what learners are doing.

The app logs structured JSON (``COACH_LOG_JSON=true``), which is right for
machines and unreadable in a terminal — a single sign-in is 200 characters of
braces. This reads those lines from stdin and prints one short line per event
that involves a person, dropping the noise (metrics scrapes, health probes,
sampler warnings) that would otherwise bury them.

Usage:
    tail -f logs/app.log | python scripts/activity_feed.py
    python scripts/activity_feed.py --no-color < logs/app.log
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime

C = {
    "dim": "\033[38;5;245m",
    "user": "\033[36m",
    "good": "\033[32m",
    "warn": "\033[33m",
    "bad": "\033[31m",
    "info": "\033[38;5;250m",
    "off": "\033[0m",
}

# Structured events worth a line, and how to say them in English.
EVENTS: dict[str, tuple[str, str]] = {
    "signup": ("good", "signed up"),
    "login": ("good", "signed in"),
    "login_failed": ("warn", "FAILED sign-in"),
    "logout_all": ("info", "signed out everywhere"),
    "password_changed": ("info", "changed password"),
    "password_change_failed": ("warn", "failed password change"),
    "ws_session_started": ("user", "started a session"),
    "ws_turn_start": ("user", "sent a turn"),
    "ws_turn_done": ("dim", "turn finished"),
    "ws_turn_skipped_short": ("warn", "take too short"),
    "ws_take_discarded": ("dim", "discarded a take"),
    "ws_session_ended": ("dim", "ended the session"),
    "assessment_ready_event": ("good", "assessment ready"),
    "reading_attempt_persist_failed": ("bad", "reading attempt NOT saved"),
    "first_audio_over_budget": ("warn", "slow first audio"),
    "degradation_transition": ("warn", "guard level changed"),
}

# HTTP lines that represent a person doing something, rather than plumbing.
HTTP = [
    (re.compile(r'"POST /users/([^/]+)/reading/score'), "user", "finished a reading"),
    (re.compile(r'"GET /users/([^/]+)/report'), "info", "downloaded a report"),
    (re.compile(r'"POST /auth/signup'), "good", "signup request"),
    (re.compile(r'"DELETE /users/([^/]+)'), "warn", "deleted an account"),
]

# Everything below is machine chatter: scrapes, probes, and a sampler warning
# that fires every second on a box without NVML.
NOISE = re.compile(r"/metrics|/healthz|nvml_sample_failed|/auth/status|/guard\b")


def _clock(raw: str | None) -> str:
    if not raw:
        return datetime.now().strftime("%H:%M:%S")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")
    except ValueError:
        return raw[11:19] if len(raw) > 19 else "--:--:--"


def _paint(colour: str, text: str, use_colour: bool) -> str:
    return f"{C[colour]}{text}{C['off']}" if use_colour else text


def format_line(line: str, *, use_colour: bool = True) -> str | None:
    """One readable line, or None when the input is not worth showing."""
    line = line.rstrip()
    if not line or NOISE.search(line):
        return None

    if line.lstrip().startswith("{"):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            return None
        event = rec.get("event", "")
        if event not in EVENTS:
            return None
        colour, label = EVENTS[event]
        who = rec.get("user_id") or rec.get("session_id", "")[:16] or "-"
        extra = []
        for key in ("audio_seconds", "sessions_revoked", "dropped_bytes", "to_level", "mode"):
            if rec.get(key) is not None:
                extra.append(f"{key}={rec[key]}")
        tail = "  " + _paint("dim", " ".join(extra), use_colour) if extra else ""
        return (
            f"{_paint('dim', _clock(rec.get('timestamp')), use_colour)}  "
            f"{_paint('user', who[:34].ljust(34), use_colour)}  "
            f"{_paint(colour, label, use_colour)}{tail}"
        )

    for pattern, colour, label in HTTP:
        m = pattern.search(line)
        if m:
            who = m.group(1) if m.groups() else "-"
            return (
                f"{_paint('dim', _clock(None), use_colour)}  "
                f"{_paint('user', who[:34].ljust(34), use_colour)}  "
                f"{_paint(colour, label, use_colour)}"
            )
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()
    use_colour = not args.no_color

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    for raw in sys.stdin:
        out = format_line(raw, use_colour=use_colour)
        if out:
            print(out, flush=True)   # unbuffered: a live feed that lags is not live
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
