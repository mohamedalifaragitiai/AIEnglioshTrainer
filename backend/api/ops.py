"""Ops endpoints for the monitoring UI: live resource stats + recommended topics."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["ops"])

_RECOMMENDED_TOPICS = [
    "Daily routine",
    "Travel & holidays",
    "Food & cooking",
    "Job interview",
    "Technology & AI",
    "Hobbies & free time",
    "Environment & climate",
    "Health & fitness",
    "Movies & books",
    "Business meeting",
]


@router.get("/stats")
def stats(request: Request) -> dict:
    """Live resource snapshot for the monitoring panel."""
    guard = request.app.state.guard
    sampler = getattr(request.app.state, "sampler", None)
    snap = guard.snapshot()

    def ratio(key: str) -> float | None:
        r = snap.get(key)
        return round(r, 4) if r is not None else None

    total = getattr(sampler, "vram_total_bytes", None) if sampler else None
    vram_ratio = snap.get("vram")
    vram_used_gb = round(vram_ratio * total / 1e9, 2) if (vram_ratio and total) else None

    registry = getattr(request.app.state, "model_registry", None)
    models = (
        [
            {"name": m.name, "kind": str(m.kind), "status": str(m.status), "vram_gb": m.vram_gb}
            for m in registry.models
        ]
        if registry
        else []
    )
    return {
        "degradation_level": guard.degradation_level,
        "ceiling": guard.ceiling,
        "soft": guard.soft,
        "resources": {k: ratio(k) for k in ("vram", "gpu_util", "ram", "cpu", "disk")},
        "vram_total_gb": round(total / 1e9, 2) if total else None,
        "vram_used_gb": vram_used_gb,
        "models": models,
        "models_loaded": sum(1 for m in models if m["status"] == "loaded"),
    }


@router.get("/topics")
def topics() -> dict:
    """Recommended practice topics (the UI also lets users type their own)."""
    return {"recommended": _RECOMMENDED_TOPICS}
