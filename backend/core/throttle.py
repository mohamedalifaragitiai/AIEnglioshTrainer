"""Failure throttling for the auth endpoints.

A login form that answers the public internet is a password-guessing target, and
PBKDF2 makes each attempt *expensive for the server* as well — unthrottled, the
same request is both a credential-stuffing vector and a way to pin a CPU that is
supposed to be running a voice turn.

In-process and in-memory on purpose: this is a single-process, single-box app
with no Redis to reach for, and a lockout that forgets itself on restart is the
right failure mode here — an operator restarting the app should not have to wait
out a lockout they triggered themselves.

The clock is injectable so tests can prove expiry without sleeping through it.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from time import monotonic

# Stop the dict growing without bound under a spray across many keys. Well above
# any legitimate concurrent-user count on this hardware.
_MAX_TRACKED_KEYS = 4096


class FailureThrottle:
    """Locks a key out after too many failures inside a rolling window."""

    def __init__(
        self,
        *,
        max_failures: int,
        window_s: float,
        lockout_s: float,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._max = max_failures
        self._window = window_s
        self._lockout = lockout_s
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[str, deque[float]] = {}
        self._locked_until: dict[str, float] = {}

    def retry_after(self, key: str) -> float:
        """Seconds until ``key`` may try again; 0.0 when it is free to proceed."""
        with self._lock:
            until = self._locked_until.get(key)
            if until is None:
                return 0.0
            remaining = until - self._clock()
            if remaining <= 0:
                # Expired: clear both sides, or the next failure would trip the
                # lockout instantly off the back of attempts already served.
                self._locked_until.pop(key, None)
                self._failures.pop(key, None)
                return 0.0
            return remaining

    def record_failure(self, key: str) -> float:
        """Count a failure. Returns the lockout in seconds if this tripped it."""
        now = self._clock()
        with self._lock:
            self._evict_if_crowded(now)
            attempts = self._failures.setdefault(key, deque())
            attempts.append(now)
            while attempts and now - attempts[0] > self._window:
                attempts.popleft()
            if len(attempts) >= self._max:
                self._locked_until[key] = now + self._lockout
                return self._lockout
            return 0.0

    def reset(self, key: str) -> None:
        """Forget a key's history — called on a successful authentication."""
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def _evict_if_crowded(self, now: float) -> None:
        """Drop entries with nothing live in them once the table gets large."""
        if len(self._failures) < _MAX_TRACKED_KEYS:
            return
        stale = [
            k
            for k, attempts in self._failures.items()
            if (not attempts or now - attempts[-1] > self._window)
            and now >= self._locked_until.get(k, 0.0)
        ]
        for k in stale:
            self._failures.pop(k, None)
            self._locked_until.pop(k, None)
        # Everything is live (a real flood): drop the oldest so memory stays bounded.
        if len(self._failures) >= _MAX_TRACKED_KEYS:
            oldest = min(self._failures, key=lambda k: self._failures[k][-1])
            self._failures.pop(oldest, None)
            self._locked_until.pop(oldest, None)
