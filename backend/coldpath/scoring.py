"""Scoring: the custom 0-5 level scale, versioned weights, and the weighted
overall score.

Phase 1 needs only the *versioned* scoring primitives so assessments can be stored
with the ``scoring_model_version`` that produced them (history stays interpretable
when weights are retuned). The full cold-path evaluators that *produce* the
per-dimension scores arrive in Phase 4; this module defines how those dimensions
combine and how an overall maps to a level.

Every change to weights or thresholds MUST bump ``SCORING_MODEL_VERSION`` and add a
new entry to the registries below — never edit an existing version in place, or
stored trends become uninterpretable.
"""

from __future__ import annotations

from dataclasses import dataclass

# The eight scored dimensions (each 0-100). Order is stable and load-bearing:
# radar/heatmap layouts and the assessments table columns follow it.
DIMENSIONS: tuple[str, ...] = (
    "pronunciation",
    "grammar",
    "vocabulary",
    "listening",
    "fluency",
    "confidence",
    "coherence",
    "relevance",
)

# Current scoring version. Bump on ANY change to weights or level thresholds.
SCORING_MODEL_VERSION = "v1"


@dataclass(frozen=True)
class ScoringModel:
    version: str
    weights: dict[str, float]
    # (upper_bound_inclusive, level) ascending; overall in [0,100] maps to a level.
    level_thresholds: tuple[tuple[int, int], ...]

    def __post_init__(self) -> None:
        missing = set(DIMENSIONS) - set(self.weights)
        if missing:
            raise ValueError(f"scoring {self.version} missing weights: {sorted(missing)}")
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"scoring {self.version} weights sum to {total}, not 1.0")

    def overall(self, scores: dict[str, float]) -> float:
        """Weighted 0-100 overall. Missing dimensions count as 0."""
        return round(sum(self.weights[d] * float(scores.get(d, 0.0)) for d in DIMENSIONS), 2)

    def level(self, overall: float) -> int:
        for upper, lvl in self.level_thresholds:
            if overall <= upper:
                return lvl
        return self.level_thresholds[-1][1]


# --- Registry of versioned scoring models (append-only) --------------------

_REGISTRY: dict[str, ScoringModel] = {
    "v1": ScoringModel(
        version="v1",
        weights={
            "pronunciation": 0.20,
            "grammar": 0.15,
            "vocabulary": 0.15,
            "listening": 0.15,
            "fluency": 0.15,
            "confidence": 0.10,
            "coherence": 0.05,
            "relevance": 0.05,
        },
        # 0-39→0, 40-54→1, 55-69→2, 70-82→3, 83-93→4, 94-100→5
        level_thresholds=((39, 0), (54, 1), (69, 2), (82, 3), (93, 4), (100, 5)),
    ),
}


def get_scoring_model(version: str = SCORING_MODEL_VERSION) -> ScoringModel:
    if version not in _REGISTRY:
        raise KeyError(f"unknown scoring_model_version: {version!r}")
    return _REGISTRY[version]


def compute_overall(scores: dict[str, float], version: str = SCORING_MODEL_VERSION) -> float:
    return get_scoring_model(version).overall(scores)


def level_for_overall(overall: float, version: str = SCORING_MODEL_VERSION) -> int:
    return get_scoring_model(version).level(overall)
