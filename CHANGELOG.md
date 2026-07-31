# Changelog

Versions follow SemVer as applied to an application, not a library — see
`config/version.py` for what each position means. The running build reports
itself at `/version` (open, like the other ops endpoints).

## [0.2.0] — 2026-07-31

### Added
- **Accounts.** `/auth/signup`, `/auth/login`, `/auth/logout`, `/auth/password`,
  `/auth/me`, `/auth/status`. Passwords are PBKDF2-HMAC-SHA256 from the stdlib;
  session tokens are stored as SHA-256 fingerprints, never in the clear. A
  learner id may be a slug or an email address, and is lowercased.
- **Enforcement behind `COACH_AUTH_REQUIRED`** (default off). When on, the data
  routes and `/ws/session` require a session, and a learner may read only their
  own profile. The machine-facing endpoints (`/healthz`, `/metrics`, `/guard`,
  `/stats`, `/models`, `/version`) stay open so monitoring keeps working.
- **Admin role** (migration 003). An admin sees every learner's profile and the
  full roster; the flag is set out-of-band via `seed_user.py --admin`, never by
  anything a caller can send.
- **Sign-in screens in both UIs** — `/login` and `/signup` in the Next.js
  dashboard, a gate plus Sign-out in the zero-dependency served page.
- `seed_user.py --password` / `--admin`, so an install can be prepared for
  enforcement without the form, and a forgotten password has a local reset path.
- `/version`, and this changelog.

### Changed
- The end-of-session dialog opens with "Thanks for your time, *name*!" and its
  primary action reads **Get my results report**.
- Claiming: signing up with an existing profile that has no password adopts it,
  so history written before accounts existed is not stranded.

### Fixed
- `COACH_AUTH_MIN_PASSWORD_LENGTH` below 4 made `Settings` refuse to validate,
  so the app would not boot at all. The floor is now 1.

## [0.1.0] — 2026-07-28

Phases 0–7: the resource guard and its 96% ceiling, SQLite profiles, model
serving through the guard, the hot voice path, the deferrable cold scoring path,
gap analysis and reports, the Next.js dashboard, and hardening (soak test, CI,
Grafana/Prometheus assets).
