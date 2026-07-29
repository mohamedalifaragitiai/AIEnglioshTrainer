"""Password hashing and session tokens — stdlib only.

PBKDF2-HMAC-SHA256 rather than bcrypt/argon2: both would be a new host-specific
wheel, and this project installs nothing outside ``uv.lock``. PBKDF2 is in
``hashlib``, is FIPS-blessed, and at a few hundred thousand rounds is a sound
choice for a local, offline, single-box deployment.

Two rules the rest of the code depends on:

* A stored credential is self-describing (algo + iterations + salt), so raising
  ``auth_hash_iterations`` later does not invalidate existing passwords — old
  hashes keep verifying at the cost they were written with.
* Session tokens are stored **hashed**. The plaintext token exists only in the
  response and the client; a leaked database therefore hands over no live
  sessions, only their fingerprints.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

ALGO = "pbkdf2_sha256"
_SALT_BYTES = 16
_TOKEN_BYTES = 32


@dataclass(frozen=True)
class PasswordHash:
    """A stored credential: everything needed to verify, nothing to reverse."""

    algo: str
    iterations: int
    salt: str
    digest: str


def hash_password(password: str, *, iterations: int, salt: str | None = None) -> PasswordHash:
    """Derive a credential for ``password``. A fresh salt is generated per call."""
    salt = salt or secrets.token_hex(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    ).hex()
    return PasswordHash(algo=ALGO, iterations=iterations, salt=salt, digest=digest)


def verify_password(password: str, stored: PasswordHash) -> bool:
    """Constant-time check of ``password`` against a stored credential.

    Verification re-derives at the *stored* iteration count, not the configured
    one, so a later cost increase does not lock anyone out.
    """
    if stored.algo != ALGO:
        return False
    candidate = hash_password(password, iterations=stored.iterations, salt=stored.salt)
    return hmac.compare_digest(candidate.digest, stored.digest)


def new_token() -> str:
    """A fresh opaque session token (URL-safe, ~256 bits)."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def token_fingerprint(token: str) -> str:
    """The value actually stored for a token. Never store the token itself."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
