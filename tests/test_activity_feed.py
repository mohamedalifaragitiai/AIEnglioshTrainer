"""The activity feed: what it shows, and what it must never hide.

A feed that drops a real event is worse than no feed — you would trust it and be
wrong. These pin both directions: human actions appear, machine chatter does not.
"""

from __future__ import annotations

import json

import pytest

from scripts.activity_feed import format_line


def line(**rec) -> str:
    rec.setdefault("timestamp", "2026-08-01T12:00:00Z")
    return json.dumps(rec)


@pytest.mark.parametrize(
    "raw, expected",
    [
        (line(event="login", user_id="abu_ali"), "signed in"),
        (line(event="login_failed", user_id="mallory"), "FAILED sign-in"),
        (line(event="signup", user_id="newbie"), "signed up"),
        (line(event="ws_turn_start", user_id="test", audio_seconds=10.0), "sent a turn"),
        (line(event="ws_turn_skipped_short", user_id="test"), "take too short"),
        (line(event="assessment_ready_event", user_id="test"), "assessment ready"),
        (line(event="password_changed", user_id="test"), "changed password"),
        (
            'INFO: 1.2.3.4:0 - "POST /users/test/reading/score HTTP/1.1" 200 OK',
            "finished a reading",
        ),
        (
            'INFO: 1.2.3.4:0 - "GET /users/test/report?format=pdf HTTP/1.1" 200 OK',
            "downloaded a report",
        ),
    ],
)
def test_human_actions_are_shown(raw, expected):
    out = format_line(raw, use_colour=False)
    assert out is not None, f"this should have been shown: {raw}"
    assert expected in out


@pytest.mark.parametrize(
    "raw",
    [
        'INFO: 127.0.0.1:1 - "GET /metrics HTTP/1.1" 200 OK',
        'INFO: 127.0.0.1:1 - "GET /healthz HTTP/1.1" 200 OK',
        'INFO: 127.0.0.1:1 - "GET /auth/status HTTP/1.1" 200 OK',
        line(event="nvml_sample_failed", error="Unknown Error"),
        "a line that is not JSON and not an access log",
        "",
    ],
)
def test_machine_chatter_is_hidden(raw):
    assert format_line(raw, use_colour=False) is None


def test_the_user_is_always_identifiable():
    """A feed of actions with no actor answers the wrong question."""
    out = format_line(line(event="login", user_id="someone@example.com"), use_colour=False)
    assert "someone@example.com" in out


def test_malformed_json_does_not_kill_the_feed():
    """One truncated line — a log written while being rotated — must not end the
    stream; the next real event still has to arrive."""
    assert format_line('{"event": "login", "user_id": ', use_colour=False) is None
    assert format_line(line(event="login", user_id="after"), use_colour=False) is not None


def test_colour_is_optional_for_piping():
    plain = format_line(line(event="login", user_id="abu_ali"), use_colour=False)
    assert "\033[" not in plain
    assert "\033[" in format_line(line(event="login", user_id="abu_ali"), use_colour=True)
