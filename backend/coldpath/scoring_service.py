"""Aggregate evaluator outputs into a versioned Assessment.

Stores each evaluator's raw payload in ``evaluator_outputs`` (kept separate so
scores can be recomputed retroactively) and the weighted, aggregated result in the
append-only ``assessments`` table, then advances the user's headline level. The
weighting/level mapping come from the versioned scoring model.
"""

from __future__ import annotations

import json

from backend.coldpath.evaluators.base import EvaluatorOutput, UtteranceForEval
from backend.coldpath.scoring import (
    DIMENSIONS,
    SCORING_MODEL_VERSION,
    get_scoring_model,
    level_for_overall,
)
from backend.core.logging import get_logger
from backend.core.util import new_id, now_iso
from backend.domain.models import Assessment
from backend.persistence.repositories import (
    AssessmentRepository,
    EvaluatorOutputRepository,
    UserRepository,
)

log = get_logger("scoring_service")


class ScoringService:
    def __init__(
        self,
        assessments: AssessmentRepository,
        evaluator_outputs: EvaluatorOutputRepository,
        users: UserRepository,
        *,
        version: str = SCORING_MODEL_VERSION,
    ):
        self.assessments = assessments
        self.evaluator_outputs = evaluator_outputs
        self.users = users
        self.version = version

    def record(self, utt: UtteranceForEval, outputs: list[EvaluatorOutput]) -> Assessment:
        dims: dict[str, float] = {}
        for out in outputs:
            # Raw payload kept verbatim for audit / recompute.
            self.evaluator_outputs.add(
                utt.utterance_id, out.evaluator, out.version, json.dumps(out.raw)
            )
            for ds in out.scores:
                if ds.dimension in DIMENSIONS:
                    dims[ds.dimension] = ds.score

        missing = [d for d in DIMENSIONS if d not in dims]
        if missing:
            log.warning("dimensions_missing", utterance_id=utt.utterance_id, missing=missing)

        overall = self._weighted_overall(dims)
        assessment = Assessment(
            assessment_id=new_id("assess"),
            user_id=utt.user_id,
            session_id=utt.session_id,
            utterance_id=utt.utterance_id,
            scoring_model_version=self.version,
            overall=overall,
            created_at=now_iso(),
            **{d: dims.get(d) for d in DIMENSIONS},
        )
        self.assessments.add(assessment)
        self.users.update(
            utt.user_id, current_level=level_for_overall(overall, self.version)
        )
        return assessment

    def _weighted_overall(self, dims: dict[str, float]) -> float:
        """Weighted overall renormalized over the dimensions actually present, so a
        skipped evaluator lowers coverage — not the score itself. When all eight are
        present this equals the standard weighted formula (weights sum to 1)."""
        model = get_scoring_model(self.version)
        present = {d: s for d, s in dims.items() if d in DIMENSIONS}
        wsum = sum(model.weights[d] for d in present)
        if wsum <= 0:
            return 0.0
        return round(sum(model.weights[d] * present[d] for d in present) / wsum, 2)
