"""User (LearnerProfile) CRUD."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.api.deps import Repositories, current_user, get_repos, owned_user_id
from backend.domain.models import User

router = APIRouter(prefix="/users", tags=["users"])

_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class CreateUserRequest(BaseModel):
    user_id: str = Field(..., description="stable slug, e.g. 'abu_ali'")
    display_name: str
    current_level: int = Field(0, ge=0, le=5)
    settings_json: str | None = None


class UpdateUserRequest(BaseModel):
    display_name: str | None = None
    current_level: int | None = Field(None, ge=0, le=5)
    settings_json: str | None = None


@router.post("", response_model=User, status_code=status.HTTP_201_CREATED)
def create_user(body: CreateUserRequest, repos: Repositories = Depends(get_repos)) -> User:
    """Create a bare profile with no password — it holds no data and cannot be logged
    into until claimed, so this stays open. Prefer POST /auth/register, which creates
    the profile and its credential together."""
    if not _SLUG.match(body.user_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "user_id must be a slug: lowercase letters, digits, '-' or '_', 2-64 chars",
        )
    if repos.users.exists(body.user_id):
        raise HTTPException(status.HTTP_409_CONFLICT, f"user {body.user_id!r} already exists")
    return repos.users.create(
        body.user_id,
        body.display_name,
        current_level=body.current_level,
        settings_json=body.settings_json,
    )


@router.get("", response_model=list[User])
def list_users(user: User = Depends(current_user)) -> list[User]:
    """Only ever the caller's own profile. Listing every learner on the box would leak
    who else practises here; the login screen uses /auth/unclaimed instead."""
    return [user]


@router.get("/{user_id}", response_model=User, dependencies=[Depends(owned_user_id)])
def get_user(user_id: str, repos: Repositories = Depends(get_repos)) -> User:
    user = repos.users.get(user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id!r} not found")
    return user


@router.patch("/{user_id}", response_model=User, dependencies=[Depends(owned_user_id)])
def update_user(
    user_id: str, body: UpdateUserRequest, repos: Repositories = Depends(get_repos)
) -> User:
    if not repos.users.exists(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id!r} not found")
    return repos.users.update(
        user_id,
        display_name=body.display_name,
        current_level=body.current_level,
        settings_json=body.settings_json,
    )


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(owned_user_id)],
)
def delete_user(user_id: str, repos: Repositories = Depends(get_repos)) -> None:
    if not repos.users.delete(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id!r} not found")
