"""Signup / login / logout.

These endpoints work whether or not ``COACH_AUTH_REQUIRED`` is on; the flag only
decides whether the *rest* of the API insists on the session they produce. That
split is deliberate — it lets a running install create accounts first and switch
enforcement on second, instead of locking every existing client out at once.

Signup **claims** a credential-less profile. The system predates auth, so the
seeded demo learner (and anything created through ``POST /users``) has a profile
and history but no password; signing up with that ``user_id`` sets its password
and keeps the history. On a local, offline, single-box install that is the
difference between keeping 29 assessments and stranding them. Once a profile has
a password, signup returns 409 and only login gets you in.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from backend.api.deps import Repositories, current_user_id, get_repos, request_token
from backend.core.logging import get_logger
from backend.core.passwords import (
    hash_password,
    new_token,
    token_fingerprint,
    verify_password,
)
from backend.domain.models import User
from config.settings import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger("auth")

# Deliberately identical for "no such user" and "wrong password": the failure
# reply should not confirm which user ids exist.
_BAD_CREDENTIALS = "invalid user id or password"


class SignupRequest(BaseModel):
    user_id: str = Field(..., description="stable slug, e.g. 'abu_ali'")
    display_name: str = Field(..., min_length=1)
    password: str


class LoginRequest(BaseModel):
    user_id: str
    password: str


class AuthSession(BaseModel):
    """What a successful signup/login hands back."""

    token: str
    expires_at: str
    user: User


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AuthStatus(BaseModel):
    auth_required: bool
    authenticated: bool
    user_id: str | None = None
    min_password_length: int
    is_admin: bool = False


def _issue(
    response: Response,
    repos: Repositories,
    settings: Settings,
    user: User,
) -> AuthSession:
    token = new_token()
    expires_at = repos.auth_sessions.create(
        user.user_id, token_fingerprint(token), ttl_hours=settings.auth_session_ttl_hours
    )
    response.set_cookie(
        settings.auth_cookie_name,
        token,
        max_age=settings.auth_session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        # Off for the default localhost install (plain http — a Secure cookie
        # would never come back and sign-in would silently not stick), on for an
        # HTTPS deployment such as `tailscale serve`. See COACH_AUTH_COOKIE_SECURE.
        secure=settings.auth_cookie_secure,
    )
    return AuthSession(token=token, expires_at=expires_at, user=user)


@router.get("/status", response_model=AuthStatus)
def auth_status(request: Request) -> AuthStatus:
    """Whether auth is enforced, and whether this caller is signed in.

    Both front-ends call this on load: it is what tells them to render a login
    gate instead of a user picker.
    """
    settings = get_settings()
    uid = current_user_id(request)
    user = Repositories.build(request.app.state.db).users.get(uid) if uid else None
    return AuthStatus(
        auth_required=settings.auth_required,
        authenticated=uid is not None,
        user_id=uid,
        min_password_length=settings.auth_min_password_length,
        is_admin=bool(user and user.is_admin),
    )


@router.post("/signup", response_model=AuthSession, status_code=status.HTTP_201_CREATED)
def signup(
    body: SignupRequest,
    response: Response,
    repos: Repositories = Depends(get_repos),
) -> AuthSession:
    # Local import: avoids a cycle (users.py imports this module's deps).
    from backend.api.users import USER_ID_RULE, USER_ID_SLUG, normalize_user_id

    settings = get_settings()
    user_id = normalize_user_id(body.user_id)
    if not USER_ID_SLUG.match(user_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, USER_ID_RULE)
    if len(body.password) < settings.auth_min_password_length:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"password must be at least {settings.auth_min_password_length} characters",
        )

    existing = repos.users.get(user_id)
    if existing is not None and repos.credentials.exists(user_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"user {user_id!r} already has an account"
        )

    if existing is None:
        user = repos.users.create(user_id, body.display_name)
        claimed = False
    else:
        # Claiming: keep the profile and its history, take the new display name.
        user = repos.users.update(user_id, display_name=body.display_name) or existing
        claimed = True

    repos.credentials.set(
        user_id,
        hash_password(body.password, iterations=settings.auth_hash_iterations),
    )
    log.info("signup", user_id=user_id, claimed_existing_profile=claimed)
    return _issue(response, repos, settings, user)


@router.post("/login", response_model=AuthSession)
def login(
    body: LoginRequest,
    response: Response,
    repos: Repositories = Depends(get_repos),
) -> AuthSession:
    from backend.api.users import normalize_user_id

    settings = get_settings()
    # Normalize here too, or an id typed with different capitalisation than at
    # signup would look like a wrong password.
    user_id = normalize_user_id(body.user_id)
    stored = repos.credentials.get(user_id)
    user = repos.users.get(user_id)
    if stored is None or user is None or not verify_password(body.password, stored):
        log.info("login_failed", user_id=user_id)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _BAD_CREDENTIALS)
    log.info("login", user_id=user_id)
    return _issue(response, repos, settings, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    repos: Repositories = Depends(get_repos),
) -> None:
    """Revoke the presented session. Idempotent — signing out twice is fine."""
    settings = get_settings()
    token = request_token(request, settings)
    if token:
        repos.auth_sessions.delete(token_fingerprint(token))
    response.delete_cookie(settings.auth_cookie_name)


@router.post("/password", response_model=AuthSession)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    repos: Repositories = Depends(get_repos),
) -> AuthSession:
    """Change your own password, proving you know the current one.

    Every other session is revoked — changing a password is what you do when you
    think someone else has it, and leaving their session live would defeat the
    point. The caller gets a fresh token back so *this* client stays signed in.

    Authenticated by token even when ``auth_required`` is off: the middleware is
    not enforcing anything then, so this endpoint checks for itself rather than
    letting an anonymous caller rewrite a password.
    """
    settings = get_settings()
    uid = current_user_id(request)
    user = repos.users.get(uid) if uid else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")

    stored = repos.credentials.get(user.user_id)
    if stored is None or not verify_password(body.current_password, stored):
        log.info("password_change_failed", user_id=user.user_id)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "current password is incorrect")

    if len(body.new_password) < settings.auth_min_password_length:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"password must be at least {settings.auth_min_password_length} characters",
        )

    repos.credentials.set(
        user.user_id,
        hash_password(body.new_password, iterations=settings.auth_hash_iterations),
    )
    revoked = repos.auth_sessions.delete_for_user(user.user_id)
    log.info("password_changed", user_id=user.user_id, sessions_revoked=revoked)
    return _issue(response, repos, settings, user)


@router.get("/me", response_model=User)
def me(request: Request, repos: Repositories = Depends(get_repos)) -> User:
    uid = current_user_id(request)
    user = repos.users.get(uid) if uid else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    return user
