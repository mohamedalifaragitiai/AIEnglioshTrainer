"""AuthService — register, claim, login, logout, and token resolution.

Policy, in one place so it is auditable:

* Creating a *profile* is harmless and stays open (it holds no data). Claiming one
  with a password is what grants access, and **reading** any profile or its history
  always requires a token for that same user.
* An existing profile with no credential row (e.g. the seeded demo learner) is
  "unclaimed": the first person to call ``claim`` sets its password. That is a
  deliberate convenience for a single-workstation install; set
  ``COACH_AUTH_ALLOW_CLAIM=false`` to require every account to be registered fresh.
* Wrong-password and unknown-user both raise the same error, so the API cannot be
  used to enumerate who has an account.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from backend.auth.passwords import hash_password, hash_token, new_token, verify_password
from backend.core.logging import get_logger
from backend.core.util import now_iso
from backend.domain.models import User
from backend.persistence.repositories import (
    AuthTokenRepository,
    CredentialRepository,
    UserRepository,
    is_unique_violation,
)
from config.settings import Settings

log = get_logger("auth")


class AuthError(Exception):
    """Authentication or registration was refused. ``code`` maps to an HTTP status."""

    def __init__(self, code: int, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass
class Issued:
    """A freshly minted session token and the user it belongs to."""

    token: str
    expires_at: str
    user: User


class AuthService:
    def __init__(
        self,
        users: UserRepository,
        credentials: CredentialRepository,
        tokens: AuthTokenRepository,
        settings: Settings,
    ):
        self.users = users
        self.credentials = credentials
        self.tokens = tokens
        self.settings = settings

    # --- helpers ----------------------------------------------------------

    def _check_password_policy(self, password: str) -> None:
        least = self.settings.auth_min_password_len
        if len(password) < least:
            raise AuthError(422, f"password must be at least {least} characters")

    def _issue(self, user: User, label: str | None) -> Issued:
        token, token_hash = new_token()
        expires = datetime.now(UTC) + timedelta(hours=self.settings.auth_token_ttl_hours)
        expires_at = expires.isoformat(timespec="seconds").replace("+00:00", "Z")
        self.tokens.add(token_hash, user.user_id, expires_at, label)
        return Issued(token=token, expires_at=expires_at, user=user)

    # --- account lifecycle ------------------------------------------------

    def register(
        self,
        user_id: str,
        display_name: str,
        password: str,
        *,
        current_level: int = 0,
        label: str | None = None,
    ) -> Issued:
        """Create a profile *and* its credential, then log in."""
        self._check_password_policy(password)
        if self.credentials.exists(user_id):
            raise AuthError(409, f"user {user_id!r} already exists")

        user = self.users.get(user_id)
        if user is None:
            try:
                user = self.users.create(
                    user_id, display_name, current_level=current_level
                )
            except Exception as exc:  # noqa: BLE001 — surface as a clean 409
                if is_unique_violation(exc):
                    raise AuthError(409, f"user {user_id!r} already exists") from exc
                raise
        self.credentials.set(user_id, *hash_password(password))
        log.info("auth_registered", user_id=user_id)
        return self._issue(user, label)

    def claim(self, user_id: str, password: str, *, label: str | None = None) -> Issued:
        """Set the password on an existing, unclaimed profile (keeps its history)."""
        if not self.settings.auth_allow_claim:
            raise AuthError(403, "claiming existing profiles is disabled")
        self._check_password_policy(password)
        user = self.users.get(user_id)
        if user is None:
            raise AuthError(404, f"user {user_id!r} not found")
        if self.credentials.exists(user_id):
            raise AuthError(409, f"user {user_id!r} already has a password — log in instead")
        self.credentials.set(user_id, *hash_password(password))
        log.info("auth_claimed", user_id=user_id)
        return self._issue(user, label)

    def login(self, user_id: str, password: str, *, label: str | None = None) -> Issued:
        cred = self.credentials.get(user_id)
        user = self.users.get(user_id)
        # One error for every failure mode: no account enumeration.
        if cred is None or user is None:
            log.info("auth_login_failed", user_id=user_id, reason="no_credential")
            raise AuthError(401, "invalid user id or password")
        if not verify_password(password, cred["algo"], cred["salt"], cred["password_hash"]):
            log.info("auth_login_failed", user_id=user_id, reason="bad_password")
            raise AuthError(401, "invalid user id or password")
        log.info("auth_login", user_id=user_id)
        return self._issue(user, label)

    def change_password(self, user_id: str, current: str, new: str) -> None:
        """Rotate the password and revoke every existing token for that user."""
        cred = self.credentials.get(user_id)
        if cred is None or not verify_password(
            current, cred["algo"], cred["salt"], cred["password_hash"]
        ):
            raise AuthError(401, "invalid user id or password")
        self._check_password_policy(new)
        self.credentials.set(user_id, *hash_password(new))
        revoked = self.tokens.revoke_all_for_user(user_id)
        log.info("auth_password_changed", user_id=user_id, tokens_revoked=revoked)

    # --- sessions ---------------------------------------------------------

    def logout(self, token: str) -> bool:
        return self.tokens.revoke(hash_token(token))

    def resolve(self, token: str) -> User | None:
        """Map a bearer token to its live user, or None."""
        user_id = self.tokens.resolve(hash_token(token), now=now_iso())
        return self.users.get(user_id) if user_id else None

    def is_claimed(self, user_id: str) -> bool:
        return self.credentials.exists(user_id)

    def unclaimed_profiles(self) -> list[User]:
        """Profiles with history but no password yet — offered on the login screen so
        an existing learner (e.g. the seeded demo) can take ownership of their data."""
        if not self.settings.auth_allow_claim:
            return []
        return [u for u in self.users.list() if not self.credentials.exists(u.user_id)]
