"""Read access to cold-path results: assessments + raw evaluator outputs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.deps import Repositories, current_user, get_repos, owned_user_id
from backend.domain.models import Assessment, EvaluatorOutput, User

router = APIRouter(tags=["assessments"])


@router.get(
    "/users/{user_id}/assessments",
    response_model=list[Assessment],
    dependencies=[Depends(owned_user_id)],
)
def list_assessments(
    user_id: str,
    version: str | None = Query(None, description="filter by scoring_model_version"),
    limit: int = Query(100, ge=1, le=1000),
    repos: Repositories = Depends(get_repos),
) -> list[Assessment]:
    if not repos.users.exists(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id!r} not found")
    return repos.assessments.list_for_user(user_id, version=version, limit=limit)


@router.get(
    "/utterances/{utterance_id}/evaluator-outputs", response_model=list[EvaluatorOutput]
)
def list_evaluator_outputs(
    utterance_id: str,
    user: User = Depends(current_user),
    repos: Repositories = Depends(get_repos),
) -> list[EvaluatorOutput]:
    # Evaluator payloads quote the learner's own speech, so check the utterance is
    # theirs before handing them over.
    utterance = repos.utterances.get(utterance_id)
    if utterance is None or utterance.user_id != user.user_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"utterance {utterance_id!r} not found"
        )
    return repos.evaluator_outputs.list_for_utterance(utterance_id)
