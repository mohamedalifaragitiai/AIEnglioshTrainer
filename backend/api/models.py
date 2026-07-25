"""Model-serving status & VRAM budget."""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.serving.base import ModelInfo, ModelRegistry

router = APIRouter(prefix="/models", tags=["models"])


def _registry(request: Request) -> ModelRegistry | None:
    return getattr(request.app.state, "model_registry", None)


@router.get("", response_model=list[ModelInfo])
def list_models(request: Request) -> list[ModelInfo]:
    registry = _registry(request)
    return registry.infos() if registry else []


@router.get("/budget")
def model_budget(request: Request) -> dict:
    registry = _registry(request)
    if registry is None:
        return {"enabled": False, "detail": "model registry not initialized"}
    return {"enabled": True, **registry.budget()}


@router.get("/llm/health")
async def llm_health(request: Request) -> dict:
    client = getattr(request.app.state, "llm_client", None)
    if client is None:
        return {"configured": False, "healthy": False}
    return {"configured": True, "base_url": client.base_url, "healthy": await client.health()}
