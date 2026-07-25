"""Adaptive study planner — turn ranked gaps into a focused plan.

Deterministic: picks the top gaps, attaches targeted activities from a per-skill
library, and sets an adaptive difficulty from the learner's recent overall trend
(raise when improving, ease when struggling). Kept off the hot path.
"""

from __future__ import annotations

from backend.coldpath.gap_analysis import GapAnalyzer
from backend.core.util import now_iso
from backend.domain.models import FocusArea, Plan
from backend.persistence.progress import ProgressService
from backend.persistence.repositories import UserRepository

# Targeted activities per skill (short, actionable).
_ACTIVITIES: dict[str, list[str]] = {
    "pronunciation": [
        "Shadow a 60-second native clip, matching word stress and rhythm.",
        "Record a minimal-pair drill (ship/sheep, bit/beat) and self-check.",
    ],
    "grammar": [
        "Do a 10-sentence tense-consistency rewrite on a past-event story.",
        "Review subject-verb agreement, then narrate your day in the present.",
    ],
    "vocabulary": [
        "Learn 5 topic words and use each in a spoken sentence.",
        "Paraphrase a short paragraph replacing common words with precise ones.",
    ],
    "listening": [
        "Summarize a 2-minute clip in three sentences, then check details.",
        "Answer targeted comprehension questions after one listen only.",
    ],
    "fluency": [
        "Do a 2-minute non-stop monologue; count and cut filler words.",
        "Read aloud at a steady 120-140 wpm without pausing on hard words.",
    ],
    "confidence": [
        "Record a 60-second answer without restarting; keep a steady pace.",
        "Practice a prepared self-introduction until it flows unhesitatingly.",
    ],
    "coherence": [
        "Structure an answer with First/Then/Finally discourse markers.",
        "Give an opinion using claim -> reason -> example -> restatement.",
    ],
    "relevance": [
        "Answer a prompt in one focused paragraph — no tangents.",
        "Restate the question in your first sentence before answering.",
    ],
}


class Planner:
    def __init__(
        self,
        gap_analyzer: GapAnalyzer,
        progress: ProgressService,
        users: UserRepository,
        *,
        focus_count: int = 3,
    ):
        self.gaps = gap_analyzer
        self.progress = progress
        self.users = users
        self.focus_count = focus_count

    def build_plan(self, user_id: str, *, horizon: str = "1_week") -> Plan:
        gaps = self.gaps.current_gaps(user_id)
        difficulty = self._difficulty(user_id)
        next_level, eta = self.progress.time_to_next_level(user_id)

        focus = [
            FocusArea(
                skill=g.skill,
                score=g.score,
                why=f"{g.gap:.0f} points below the {g.target:.0f} target "
                f"(rank {g.rank} by weighted impact).",
                activities=_ACTIVITIES.get(g.skill, []),
            )
            for g in gaps[: self.focus_count]
            if g.gap > 0
        ]

        if focus:
            skills = ", ".join(f.skill for f in focus)
            summary = (
                f"Focus this {horizon.replace('_', ' ')} on {skills}. "
                f"Practicing at difficulty {difficulty:.2f}."
            )
        else:
            summary = "All skills are near target — keep practicing to consolidate."

        return Plan(
            user_id=user_id,
            created_at=now_iso(),
            horizon=horizon,
            difficulty=difficulty,
            next_level=next_level,
            estimated_days_to_next_level=eta,
            focus_areas=focus,
            summary=summary,
        )

    def _difficulty(self, user_id: str) -> float:
        """Adaptive difficulty in [0,1]: anchored on latest overall, nudged by the
        recent trend (up = harder, down = easier)."""
        latest = self.gaps.assessments.latest_for_user(user_id)
        base = (latest.overall / 100.0) if (latest and latest.overall is not None) else 0.4
        trend = self.progress.skill_trend(user_id, "overall", days=30)
        nudge = 0.0
        if len(trend) >= 2:
            nudge = 0.05 if trend[-1].value >= trend[0].value else -0.05
        return round(max(0.0, min(1.0, base + nudge)), 2)
