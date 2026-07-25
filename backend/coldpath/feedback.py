"""Post-session feedback — assembled from stored assessments + evaluator outputs.

Strengths/weaknesses from the latest per-dimension scores; concrete grammar
corrections and vocabulary suggestions pulled from the batched LLM evaluator's raw
payload (present only once the LLM evaluator has run); a pronunciation tip keyed to
the score; plus level and time-to-next-level. Never blocks a live turn — read-only.
"""

from __future__ import annotations

import json

from backend.coldpath.scoring import DIMENSIONS
from backend.domain.models import Feedback
from backend.persistence.progress import ProgressService
from backend.persistence.repositories import (
    AssessmentRepository,
    EvaluatorOutputRepository,
    UserRepository,
)


def _pronunciation_tip(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 85:
        return "Pronunciation is strong — refine intonation on longer sentences."
    if score >= 70:
        return "Good clarity; focus on word stress in multi-syllable words."
    return "Slow down slightly and over-articulate vowel contrasts (ship/sheep)."


class FeedbackBuilder:
    def __init__(
        self,
        assessments: AssessmentRepository,
        evaluator_outputs: EvaluatorOutputRepository,
        users: UserRepository,
        progress: ProgressService,
    ):
        self.assessments = assessments
        self.evaluator_outputs = evaluator_outputs
        self.users = users
        self.progress = progress

    def build(self, user_id: str) -> Feedback:
        user = self.users.get(user_id)
        level = user.current_level if user else 0
        next_level, eta = self.progress.time_to_next_level(user_id)
        fb = Feedback(
            user_id=user_id,
            current_level=level,
            next_level=next_level,
            estimated_days_to_next_level=eta,
        )

        latest = self.assessments.latest_for_user(user_id)
        if latest is None:
            return fb
        fb.overall = latest.overall

        scored = [(d, getattr(latest, d)) for d in DIMENSIONS if getattr(latest, d) is not None]
        scored.sort(key=lambda kv: kv[1], reverse=True)
        fb.strengths = [d for d, s in scored[:2] if s >= 65]
        fb.weaknesses = [d for d, s in reversed(scored[-2:]) if s < 65]
        fb.pronunciation_tip = _pronunciation_tip(latest.pronunciation)

        if latest.utterance_id:
            for out in self.evaluator_outputs.list_for_utterance(latest.utterance_id):
                try:
                    raw = json.loads(out.payload_json)
                except (json.JSONDecodeError, TypeError):
                    continue
                grammar = raw.get("grammar") if isinstance(raw, dict) else None
                if isinstance(grammar, dict) and isinstance(grammar.get("errors"), list):
                    fb.corrections.extend(grammar["errors"][:5])
                vocab = raw.get("vocabulary") if isinstance(raw, dict) else None
                if isinstance(vocab, dict) and isinstance(vocab.get("suggestions"), list):
                    fb.vocabulary_suggestions.extend(vocab["suggestions"][:5])
        return fb
