"""User (LearnerProfile) CRUD."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.api.deps import Repositories, current_user_id, get_repos
from backend.domain.models import User
from config.settings import get_settings

router = APIRouter(prefix="/users", tags=["users"])

# Public: /auth/signup validates new account ids against the same rule.
#
# Email addresses are allowed (people reach for one at a login screen), hence
# '@', '.' and '+'. What is still excluded matters: no '/', '\' or ':', and the
# first character must be alphanumeric — `user_id` is interpolated into a report
# filename in coldpath/insights.py, so an id like '..' or 'a/b' would escape the
# report directory. Ids are lowercased before they get here, so 'A@x' and 'a@x'
# cannot become two accounts.
USER_ID_SLUG = re.compile(r"^[a-z0-9][a-z0-9._@+-]{1,63}$")

USER_ID_RULE = (
    "user_id must be 2-64 characters, start with a letter or digit, and contain "
    "only letters, digits, '.', '_', '-', '+' or '@' (an email address is fine)"
)


def normalize_user_id(user_id: str) -> str:
    """Trim and lowercase, so 'Abu_Ali ' and 'abu_ali' are the same account."""
    return user_id.strip().lower()


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
    user_id = normalize_user_id(body.user_id)
    if not USER_ID_SLUG.match(user_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, USER_ID_RULE)
    if repos.users.exists(user_id):
        raise HTTPException(status.HTTP_409_CONFLICT, f"user {user_id!r} already exists")
    return repos.users.create(
        user_id,
        body.display_name,
        current_level=body.current_level,
        settings_json=body.settings_json,
    )


@router.get("", response_model=list[User])
def list_users(request: Request, repos: Repositories = Depends(get_repos)) -> list[User]:
    """All profiles — or just your own once auth is enforced.

    Both UIs drive their learner picker off this list. With auth on, handing back
    every profile would turn that picker into a roster of other people's names,
    so it narrows to the signed-in learner.
    """
    if get_settings().auth_required:
        uid = current_user_id(request)
        user = repos.users.get(uid) if uid else None
        return [user] if user else []
    return repos.users.list()


@router.get("/{user_id}", response_model=User)
def get_user(user_id: str, repos: Repositories = Depends(get_repos)) -> User:
    user = repos.users.get(user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id!r} not found")
    return user


@router.patch("/{user_id}", response_model=User)
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


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: str, repos: Repositories = Depends(get_repos)) -> None:
    if not repos.users.delete(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id!r} not found")
