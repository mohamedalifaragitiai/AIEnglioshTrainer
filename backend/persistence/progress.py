"""Progress queries — the longitudinal views over a learner's stored history.

Answers the questions the spec requires per user: skill trend over time, streak,
and a time-to-next-level estimate from the recent overall-score slope. All derived
from stored ``assessments``/``sessions`` — nothing re-runs inference.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from backend.coldpath.scoring import (
    DIMENSIONS,
    SCORING_MODEL_VERSION,
    get_scoring_model,
)
from backend.domain.models import ProgressOverview, SkillPoint
from backend.persistence.repositories import (
    AssessmentRepository,
    SessionRepository,
    UserRepository,
)


class ProgressService:
    def __init__(
        self,
        users: UserRepository,
        sessions: SessionRepository,
        assessments: AssessmentRepository,
    ):
        self.users = users
        self.sessions = sessions
        self.assessments = assessments

    # --- skill trend -------------------------------------------------------

    def skill_trend(
        self, user_id: str, skill: str, *, days: int | None = 30
    ) -> list[SkillPoint]:
        """Points (created_at, score) for one dimension, optionally within `days`."""
        if skill not in DIMENSIONS and skill != "overall":
            raise ValueError(f"unknown skill {skill!r}; use one of {DIMENSIONS} or 'overall'")
        since = None
        if days is not None:
            since = (datetime.now().astimezone() - timedelta(days=days)).isoformat()
        rows = self.assessments.list_for_user(user_id, since=since)
        out: list[SkillPoint] = []
        for a in rows:
            val = getattr(a, skill)
            if val is not None:
                out.append(SkillPoint(created_at=a.created_at, value=float(val)))
        return out

    # --- streak ------------------------------------------------------------

    def streak_days(self, user_id: str) -> int:
        """Consecutive calendar days (UTC) with at least one session, ending at the
        most recent practice day."""
        sessions = self.sessions.list_for_user(user_id, limit=10_000)
        days: set[date] = set()
        for s in sessions:
            try:
                days.add(datetime.fromisoformat(s.started_at).date())
            except ValueError:
                continue
        if not days:
            return 0
        cur = max(days)
        streak = 0
        while cur in days:
            streak += 1
            cur = cur - timedelta(days=1)
        return streak

    def recompute_and_store_streak(self, user_id: str) -> int:
        streak = self.streak_days(user_id)
        self.users.update(user_id, streak_days=streak)
        return streak

    # --- time to next level ------------------------------------------------

    def _next_level_target(self, overall: float, version: str) -> tuple[int, float] | None:
        """(next_level, overall needed to reach it) or None if already at max."""
        model = get_scoring_model(version)
        lvl = model.level(overall)
        if lvl >= model.level_thresholds[-1][1]:
            return None
        for upper, level in model.level_thresholds:
            if level == lvl:
                return lvl + 1, float(upper) + 1.0
        return None

    def time_to_next_level(
        self, user_id: str, *, version: str = SCORING_MODEL_VERSION, min_points: int = 3
    ) -> tuple[int | None, float | None]:
        """Estimate (next_level, days_to_reach) from the recent overall slope.

        Returns (None, None) when there isn't enough data, the learner is at the
        top level, or the trend is flat/declining (no positive ETA).
        """
        rows = [
            a
            for a in self.assessments.list_for_user(user_id, version=version)
            if a.overall is not None
        ]
        if len(rows) < min_points:
            return None, None

        latest_overall = float(rows[-1].overall)
        target = self._next_level_target(latest_overall, version)
        if target is None:
            return None, None
        next_level, needed = target

        # Least-squares slope of overall vs. elapsed days.
        t0 = datetime.fromisoformat(rows[0].created_at)
        xs, ys = [], []
        for a in rows:
            dt = (datetime.fromisoformat(a.created_at) - t0).total_seconds() / 86400.0
            xs.append(dt)
            ys.append(float(a.overall))
        slope = _linreg_slope(xs, ys)
        if slope is None or slope <= 1e-9:
            return next_level, None

        days = (needed - latest_overall) / slope
        return next_level, round(max(0.0, days), 1)

    # --- overview ----------------------------------------------------------

    def overview(self, user_id: str) -> ProgressOverview | None:
        user = self.users.get(user_id)
        if user is None:
            return None
        latest = self.assessments.latest_for_user(user_id)
        next_level, eta = self.time_to_next_level(user_id)
        return ProgressOverview(
            user_id=user.user_id,
            display_name=user.display_name,
            current_level=user.current_level,
            streak_days=user.streak_days,
            latest_overall=(latest.overall if latest else None),
            latest_scores=(latest.dimensions() if latest else {}),
            assessments_count=self.assessments.count_for_user(user_id),
            next_level=next_level,
            estimated_days_to_next_level=eta,
        )


def _linreg_slope(xs: list[float], ys: list[float]) -> float | None:
    """Slope of the least-squares line y = a + b·x, or None if x has no spread."""
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return None
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return num / denom
