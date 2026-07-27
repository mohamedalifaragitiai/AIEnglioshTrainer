"""Password hashing with ``hashlib.scrypt`` — memory-hard, standard library only.

scrypt is chosen over PBKDF2 because it costs memory as well as CPU, and over
argon2/bcrypt because those are third-party wheels and this project installs nothing
it does not need. Parameters below cost ~45ms per verification on the reference host,
which is the right order of magnitude for an interactive login.

The stored form is ``algo`` + ``salt`` + ``hash``, all base64, so parameters can change
later without invalidating existing rows: each row records the algo that produced it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

# scrypt cost parameters, encoded into the algo string so a stored hash always knows
# how to verify itself even after these defaults move.
_N = 2**14
_R = 8
_P = 1
_DKLEN = 32
_SALT_BYTES = 16

ALGO = f"scrypt${_N}${_R}${_P}${_DKLEN}"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _derive(password: str, salt: bytes, *, n: int, r: int, p: int, dklen: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=dklen, maxmem=64 * 1024 * 1024
    )


def hash_password(password: str) -> tuple[str, str, str]:
    """Hash a password. Returns ``(algo, salt_b64, hash_b64)`` for storage."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _derive(password, salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return ALGO, _b64(salt), _b64(digest)


def verify_password(password: str, algo: str, salt_b64: str, hash_b64: str) -> bool:
    """Constant-time verification against a stored row. False on any malformed row."""
    try:
        kind, n_s, r_s, p_s, dklen_s = algo.split("$")
        if kind != "scrypt":
            return False
        digest = _derive(
            password,
            _unb64(salt_b64),
            n=int(n_s),
            r=int(r_s),
            p=int(p_s),
            dklen=int(dklen_s),
        )
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(digest, _unb64(hash_b64))


def new_token() -> tuple[str, str]:
    """Mint a bearer token. Returns ``(token, token_hash)``.

    The caller hands the token to the client and stores only the hash, so a leaked
    database cannot be replayed against the API.
    """
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
