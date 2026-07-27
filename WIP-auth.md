# WIP: auth + per-user dashboards (branch `feat/auth-and-dashboards`)

Stopped mid-task on 2026-07-27. **This branch is not green** — the backend is done and
verified, but the older API tests still call user-scoped routes without a token, so the
suite fails until they are migrated. `main` is untouched and green; nothing here is
merged.

## Done and verified

- **`backend/auth/`** — `passwords.py` (scrypt via `hashlib`, no new dependency:
  ~45ms/verify, stores `algo$N$r$p$dklen` so parameters can move later) and
  `service.py` (`AuthService`: register / claim / login / logout / change_password /
  resolve).
- **Migration 002** — `credentials` (one row per user; absent = profile unclaimed) and
  `auth_tokens` (SHA-256 of the token only, `revoked_at` for logout).
- **`backend/api/auth.py`** — `/auth/register`, `/auth/claim`, `/auth/unclaimed`,
  `/auth/login`, `/auth/logout`, `/auth/me`, `/auth/password`. Wired in `main.py`.
- **Ownership enforced everywhere** — `current_user`, `owned_user_id`,
  `owned_session_id` in `api/deps.py`; applied to `users`, `sessions`, `assessments`,
  `progress`, `insights`, `dev`. `GET /users` now returns only the caller.
  Cross-user access returns **404, not 403** (403 would confirm the account exists).
- **WebSocket authenticates by token**, not `?user_id=` — the first frame must be
  `{"type":"auth","token":"..."}`, bounded by `ws_auth_timeout_s` (10s) so an
  unauthenticated socket cannot hold a session slot. Close codes: 4401 bad/missing
  token, 4400 malformed, 4408 timeout.
- **Settings**: `auth_token_ttl_hours` (336), `auth_min_password_len` (8),
  `auth_allow_claim` (true), `ws_auth_timeout_s` (10).
- **Smoke test: 31/31 pass** — including that Bob cannot read Alice's profile,
  assessments, progress, gaps, report, sessions or utterances; logout revokes only the
  presented token; password change revokes all of them; no account enumeration
  (wrong password and unknown user both 401).

## Next step (start here)

Migrate the remaining API tests to pass a token. `tests/conftest.py` already has the
helpers — `register_user(client, uid)` returns `(uid, headers)`, and
`auth_headers(client, uid)` logs an existing account in. `tests/test_profiles_api.py`
is already fully migrated; copy that pattern.

Still to migrate (count of client calls needing headers):
`test_api.py` (3), `test_insights_api.py` (12), `test_frontend.py` (5),
`test_cors.py` (1), `test_ws_session.py` (8 — also needs the auth frame sent before
anything else, or `_receive_within` will fail the test at its 15s deadline).

Then: `pytest`, `ruff check .`, and add `tests/test_auth.py` covering what the
scratch smoke test covers.

## Remaining scope after that

1. History-over-time API — per-day/per-session rollups over a date range.
2. Reports — every point out of 100, overall + band, per-dimension evidence, trend.
3. Served UI (`frontend/index.html`) — login/logout gate, token storage, date-range
   dashboard, detailed report. **Do this one first of the two front-ends.**
4. Next.js port (`frontend-next/`) — same, keeping parity.

## Gotchas that cost time already

- `pyproject` sets `addopts = "-q"`. Passing `-q` again makes it `-qq` and hides the
  `N passed` line.
- Adding a WS handshake without a timeout deadlocks the suite silently — that is why
  `ws_auth_timeout_s` exists. Any new WS state must still answer every client frame.
