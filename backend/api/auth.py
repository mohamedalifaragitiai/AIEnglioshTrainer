"""Auth endpoints: register, claim, login, logout, me, change-password.

The token returned by register/claim/login is an opaque bearer string. Send it as
``Authorization: Bearer <token>`` on REST calls, and as the first WebSocket message
(``{"type": "auth", "token": ...}``) when opening a practice session.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from backend.api.deps import current_user, get_auth
from backend.auth.service import AuthError, AuthService, Issued
from backend.domain.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_bearer = HTTPBearer(auto_error=False)


class RegisterRequest(BaseModel):
    user_id: str = Field(..., description="stable slug, e.g. 'abu_ali'")
    display_name: str
    password: str
    current_level: int = Field(0, ge=0, le=5)


class LoginRequest(BaseModel):
    user_id: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class TokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_at: str
    user: User


class UnclaimedProfile(BaseModel):
    user_id: str
    display_name: str
    current_level: int


def _token_response(issued: Issued) -> TokenResponse:
    return TokenResponse(token=issued.token, expires_at=issued.expires_at, user=issued.user)


def _http(exc: AuthError) -> HTTPException:
    return HTTPException(exc.code, exc.detail)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, auth: AuthService = Depends(get_auth)) -> TokenResponse:
    if not _SLUG.match(body.user_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "user_id must be a slug: lowercase letters, digits, '-' or '_', 2-64 chars",
        )
    try:
        return _token_response(
            auth.register(
                body.user_id,
                body.display_name,
                body.password,
                current_level=body.current_level,
            )
        )
    except AuthError as exc:
        raise _http(exc) from exc


@router.post("/claim", response_model=TokenResponse)
def claim(body: LoginRequest, auth: AuthService = Depends(get_auth)) -> TokenResponse:
    """Set the password on an existing profile that has none, keeping its history."""
    try:
        return _token_response(auth.claim(body.user_id, body.password))
    except AuthError as exc:
        raise _http(exc) from exc


@router.get("/unclaimed", response_model=list[UnclaimedProfile])
def unclaimed(auth: AuthService = Depends(get_auth)) -> list[UnclaimedProfile]:
    """Profiles that exist but have no password yet, so the login screen can offer
    them for claiming. Names only — no history is exposed without a token."""
    return [
        UnclaimedProfile(
            user_id=u.user_id, display_name=u.display_name, current_level=u.current_level
        )
        for u in auth.unclaimed_profiles()
    ]


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, auth: AuthService = Depends(get_auth)) -> TokenResponse:
    try:
        return _token_response(auth.login(body.user_id, body.password))
    except AuthError as exc:
        raise _http(exc) from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    auth: AuthService = Depends(get_auth),
) -> None:
    """Revoke the presented token. Idempotent: an already-dead token still returns 204."""
    if creds and creds.credentials:
        auth.logout(creds.credentials)


@router.get("/me", response_model=User)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(current_user),
    auth: AuthService = Depends(get_auth),
) -> None:
    """Rotate the password. Every existing token for this user is revoked, so other
    devices are logged out."""
    try:
        auth.change_password(user.user_id, body.current_password, body.new_password)
    except AuthError as exc:
        raise _http(exc) from exc
