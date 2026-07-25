"""Gap analysis — rank a learner's weakest, highest-impact skills.

Severity blends *shortfall* (how far below target) with *importance* (the skill's
scoring weight, relative to the heaviest weight), so a small gap on pronunciation
can outrank a larger gap on coherence. Deterministic; no LLM. Snapshots are stored
so "which gap improved most this month" is answerable over time.
"""

from __future__ import annotations

import json

from backend.coldpath.scoring import DIMENSIONS, SCORING_MODEL_VERSION, get_scoring_model
from backend.domain.models import GapItem, ImprovementItem
from backend.persistence.repositories import (
    AssessmentRepository,
    GapSnapshotRepository,
)


class GapAnalyzer:
    def __init__(
        self,
        assessments: AssessmentRepository,
        gaps: GapSnapshotRepository,
        *,
        target: float = 85.0,
        version: str = SCORING_MODEL_VERSION,
    ):
        self.assessments = assessments
        self.gaps = gaps
        self.target = target
        self.version = version

    def current_gaps(self, user_id: str) -> list[GapItem]:
        latest = self.assessments.latest_for_user(user_id)
        if latest is None:
            return []
        weights = get_scoring_model(self.version).weights
        max_w = max(weights.values())

        items: list[GapItem] = []
        for skill in DIMENSIONS:
            score = getattr(latest, skill)
            if score is None:
                continue
            gap = max(0.0, self.target - float(score))
            importance = weights[skill] / max_w          # 0..1
            severity = round(importance * (gap / self.target), 4)  # 0..1
            items.append(
                GapItem(
                    skill=skill,
                    score=round(float(score), 1),
                    target=self.target,
                    gap=round(gap, 1),
                    severity=severity,
                    rank=0,
                )
            )
        items.sort(key=lambda g: g.severity, reverse=True)
        for i, item in enumerate(items, start=1):
            item.rank = i
        return items

    def snapshot(self, user_id: str) -> dict[str, float]:
        """Compute and persist the current gap vector (ranked {skill: severity})."""
        gaps = self.current_gaps(user_id)
        vector = {g.skill: g.severity for g in gaps}
        self.gaps.add(user_id, json.dumps(vector))
        return vector

    def improvement(self, user_id: str, *, days: int = 30) -> list[ImprovementItem]:
        """Per-skill score change: latest vs the assessment nearest `days` ago.

        Derived from stored assessments (robust even with no gap snapshots yet).
        """
        rows = self.assessments.list_for_user(user_id)
        if len(rows) < 2:
            return []
        from datetime import datetime, timedelta

        cutoff = (datetime.now().astimezone() - timedelta(days=days)).isoformat()
        baseline = None
        for a in rows:
            if a.created_at <= cutoff:
                baseline = a  # latest row at/before the cutoff
        baseline = baseline or rows[0]  # else the earliest we have
        latest = rows[-1]

        items: list[ImprovementItem] = []
        for skill in DIMENSIONS:
            now = getattr(latest, skill)
            then = getattr(baseline, skill)
            if now is None or then is None:
                continue
            items.append(
                ImprovementItem(
                    skill=skill,
                    then=round(float(then), 1),
                    now=round(float(now), 1),
                    delta=round(float(now) - float(then), 1),
                )
            )
        items.sort(key=lambda i: i.delta, reverse=True)
        return items
