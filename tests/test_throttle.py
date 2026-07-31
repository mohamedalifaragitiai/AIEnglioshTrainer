"""Failed-login throttling — the unit, and the endpoints that use it."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.core.throttle import FailureThrottle
from backend.core.util import new_id
from backend.main import app


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def throttle(clock: FakeClock) -> FailureThrottle:
    return FailureThrottle(max_failures=3, window_s=60, lockout_s=120, clock=clock)


def test_locks_out_after_the_threshold(throttle: FailureThrottle):
    assert throttle.retry_after("k") == 0.0
    throttle.record_failure("k")
    throttle.record_failure("k")
    assert throttle.retry_after("k") == 0.0, "under the limit must stay open"
    assert throttle.record_failure("k") == 120
    assert throttle.retry_after("k") == 120


def test_lockout_expires_and_does_not_re_trip_instantly(
    throttle: FailureThrottle, clock: FakeClock
):
    for _ in range(3):
        throttle.record_failure("k")
    clock.advance(121)
    assert throttle.retry_after("k") == 0.0
    # The expired attempts must be forgotten too, or one more failure would
    # re-lock immediately off the back of guesses already paid for.
    assert throttle.record_failure("k") == 0.0


def test_failures_outside_the_window_do_not_accumulate(
    throttle: FailureThrottle, clock: FakeClock
):
    throttle.record_failure("k")
    throttle.record_failure("k")
    clock.advance(61)
    assert throttle.record_failure("k") == 0.0, "old failures should have aged out"


def test_success_clears_the_history(throttle: FailureThrottle):
    throttle.record_failure("k")
    throttle.record_failure("k")
    throttle.reset("k")
    assert throttle.record_failure("k") == 0.0


def test_keys_are_independent(throttle: FailureThrottle):
    for _ in range(3):
        throttle.record_failure("a")
    assert throttle.retry_after("a") > 0
    assert throttle.retry_after("b") == 0.0


# --- the endpoints ---------------------------------------------------------


def _reset_endpoint_throttle():
    from backend.api.auth import _throttle

    _throttle.cache_clear()


def test_repeated_bad_logins_start_answering_429():
    """A public login form without this is a password-guessing target."""
    _reset_endpoint_throttle()
    try:
        with TestClient(app) as client:
            uid = "t" + new_id()[:10]
            client.post(
                "/auth/signup",
                json={"user_id": uid, "display_name": "T", "password": "a-real-password"},
            )
            codes = [
                client.post(
                    "/auth/login", json={"user_id": uid, "password": "wrong"}
                ).status_code
                for _ in range(7)
            ]
            assert codes[0] == 401, codes
            assert 429 in codes, f"never throttled: {codes}"

            # Locked out means locked out — the right password does not skip it,
            # or an attacker learns when they have guessed correctly.
            r = client.post("/auth/login", json={"user_id": uid, "password": "a-real-password"})
            assert r.status_code == 429
            assert int(r.headers["Retry-After"]) > 0
    finally:
        _reset_endpoint_throttle()


def test_a_successful_login_is_not_throttled():
    _reset_endpoint_throttle()
    try:
        with TestClient(app) as client:
            uid = "t" + new_id()[:10]
            client.post(
                "/auth/signup",
                json={"user_id": uid, "display_name": "T", "password": "a-real-password"},
            )
            for _ in range(6):
                r = client.post(
                    "/auth/login", json={"user_id": uid, "password": "a-real-password"}
                )
                assert r.status_code == 200
    finally:
        _reset_endpoint_throttle()
