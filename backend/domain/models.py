"""Domain aggregates (DDD) as pydantic models.

These are the persisted shapes and the API response shapes — one definition,
validated on the way in and serialized on the way out. Mirrors the schema in
``references/data-model.md``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from backend.coldpath.scoring import DIMENSIONS


class Role(StrEnum):
    LEARNER = "learner"
    COACH = "coach"


class SessionMode(StrEnum):
    FREE = "free"
    INTERVIEW = "interview"
    IELTS = "ielts"
    BUSINESS = "business"
    GENERAL = "general"
    # Read-aloud practice. A distinct mode rather than reusing FREE: these
    # sessions have learner turns and no coach reply, so the conversation views
    # exclude them and the Reading tab owns them instead.
    READING = "reading"


class User(BaseModel):
    """LearnerProfile root — the durable per-user record."""

    user_id: str
    display_name: str
    created_at: str
    current_level: int = 0
    streak_days: int = 0
    settings_json: str | None = None
    # A coach/administrator: sees every learner's profile instead of only their
    # own. Defaulted so rows written before migration 003 still map.
    is_admin: bool = False
    # False until the learner picks a starting level themselves. current_level
    # alone cannot express this: 0 is both "Beginner" and "never asked".
    level_selected: bool = False


class Session(BaseModel):
    session_id: str
    user_id: str
    mode: SessionMode = SessionMode.FREE
    started_at: str
    ended_at: str | None = None
    difficulty: float | None = None


class Utterance(BaseModel):
    utterance_id: str
    session_id: str
    user_id: str
    role: Role
    audio_path: str | None = None
    transcript: str | None = None
    stt_confidence: float | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    created_at: str


class Assessment(BaseModel):
    """Aggregated, versioned per-dimension scores. Append-only — never mutated."""

    assessment_id: str
    user_id: str
    session_id: str | None = None
    utterance_id: str | None = None
    scoring_model_version: str
    # per-dimension scores 0-100
    pronunciation: float | None = None
    grammar: float | None = None
    vocabulary: float | None = None
    listening: float | None = None
    fluency: float | None = None
    confidence: float | None = None
    coherence: float | None = None
    relevance: float | None = None
    overall: float | None = None
    created_at: str

    def dimensions(self) -> dict[str, float | None]:
        return {d: getattr(self, d) for d in DIMENSIONS}


class EvaluatorOutput(BaseModel):
    """Raw evaluator payload, kept separate from aggregated scores for recompute."""

    id: str
    utterance_id: str | None = None
    evaluator: str
    version: str
    payload_json: str
    created_at: str


class GapSnapshot(BaseModel):
    id: str
    user_id: str
    taken_at: str
    gaps_json: str  # ranked {skill: severity}


class SkillPoint(BaseModel):
    """One point on a skill trend line."""

    created_at: str
    value: float


class GapItem(BaseModel):
    """One ranked skill gap: how far below target and how much it matters."""

    skill: str
    score: float
    target: float
    gap: float           # points below target (>= 0)
    severity: float      # weighted 0..1 (importance x shortfall) — the ranking key
    rank: int


class ImprovementItem(BaseModel):
    skill: str
    then: float
    now: float
    delta: float         # now - then (positive = improved)


class FocusArea(BaseModel):
    skill: str
    score: float
    why: str
    activities: list[str]


class Plan(BaseModel):
    user_id: str
    created_at: str
    horizon: str
    difficulty: float                       # 0..1 adaptive difficulty
    next_level: int | None = None
    estimated_days_to_next_level: float | None = None
    focus_areas: list[FocusArea] = Field(default_factory=list)
    summary: str = ""


class Feedback(BaseModel):
    user_id: str
    overall: float | None = None
    current_level: int = 0
    next_level: int | None = None
    estimated_days_to_next_level: float | None = None
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    corrections: list[dict] = Field(default_factory=list)     # {text, correction, type}
    vocabulary_suggestions: list[str] = Field(default_factory=list)
    pronunciation_tip: str | None = None


class ProgressOverview(BaseModel):
    """Everything the dashboard needs for a user's headline view."""

    user_id: str
    display_name: str
    current_level: int
    streak_days: int
    latest_overall: float | None = None
    latest_scores: dict[str, float | None] = Field(default_factory=dict)
    assessments_count: int = 0
    # The level the latest score implies, which is not always current_level:
    # a learner picks a starting level themselves, and the cold path writes the
    # earned one. When they disagree the UI has to say so rather than show
    # "Level 3" beside "reach level 2".
    scored_level: int | None = None
    next_level: int | None = None
    estimated_days_to_next_level: float | None = None
