"""Per-conversation analysis: what happened in one practice session.

The cold path already scores each utterance and keeps the raw evaluator output.
What was missing was the view a learner actually wants after speaking: this is
what you said, here is what was wrong with it, here is how you scored, and here
is what to work on next.

Everything is assembled from stored rows — no LLM call. A report a learner opens
five times should not cost five inference runs, and it must still render when
the model server is down or the guard has deferred scoring.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from backend.coldpath.scoring import DIMENSIONS
from backend.domain.models import Assessment, Role, SessionMode
from backend.persistence.db import Database
from backend.persistence.repositories import (
    AssessmentRepository,
    EvaluatorOutputRepository,
    SessionRepository,
    UtteranceRepository,
)

# Actionable per dimension, chosen by band. Deliberately concrete: "work on
# fluency" tells a learner nothing they did not already know.
_TIPS: dict[str, tuple[str, str]] = {
    "pronunciation": (
        "Record one sentence, listen back, and compare it to a native clip of the "
        "same words — focus on vowel length (ship/sheep, full/fool).",
        "Refine word stress in longer words: say them syllable by syllable, then at speed.",
    ),
    "grammar": (
        "Re-say each corrected sentence below out loud twice — once reading, once from memory.",
        "Pick one tense and narrate your day in it for two minutes.",
    ),
    "vocabulary": (
        "Swap three basic words you used (good, thing, very) for the "
        "alternatives suggested below.",
        "Collect five words from this topic and use each in a new sentence tomorrow.",
    ),
    "listening": (
        "Ask the coach to repeat when unsure — checking beats guessing, and the "
        "score follows.",
        "Shadow a 30-second clip: play, pause, repeat exactly.",
    ),
    "fluency": (
        "Aim for longer runs between pauses: plan the whole sentence before starting it.",
        "Practise linking words (and then, because of that) to keep sentences moving.",
    ),
    "confidence": (
        "Replace filler pauses with a full stop: a finished short sentence "
        "sounds surer than a long hesitant one.",
        "Speak 10% louder and slower; both read as confidence.",
    ),
    "coherence": (
        "Structure answers as point → reason → example before you start speaking.",
        "Use signposts (first, however, so) to connect your ideas explicitly.",
    ),
    "relevance": (
        "Answer the question asked in your first sentence, then add detail.",
        "Re-read the question in your head before replying; drift usually starts at word one.",
    ),
}

_STRONG = 75.0
_WEAK = 60.0


def _top(scores: dict[str, float], *, best: bool) -> list[str]:
    """Best three at or above _STRONG, or worst three below _WEAK."""
    if best:
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        return [d for d, v in ranked if v >= _STRONG][:3]
    ranked = sorted(scores.items(), key=lambda kv: kv[1])
    return [d for d, v in ranked if v < _WEAK][:3]


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _mean_scores(assessments: list[Assessment]) -> dict[str, float]:
    out: dict[str, float] = {}
    for dim in DIMENSIONS:
        vals = [getattr(a, dim) for a in assessments if getattr(a, dim) is not None]
        if vals:
            out[dim] = round(sum(vals) / len(vals), 1)
    return out


def _duration_s(started_at: str | None, ended_at: str | None) -> float | None:
    if not started_at or not ended_at:
        return None
    try:
        return round(
            (datetime.fromisoformat(ended_at) - datetime.fromisoformat(started_at)).total_seconds(),
            1,
        )
    except ValueError:
        return None


class ConversationAnalyzer:
    def __init__(self, db: Database):
        self.sessions = SessionRepository(db)
        self.utterances = UtteranceRepository(db)
        self.assessments = AssessmentRepository(db)
        self.evaluator_outputs = EvaluatorOutputRepository(db)

    # --- one conversation --------------------------------------------------

    def analyze(self, session_id: str) -> dict | None:
        session = self.sessions.get(session_id)
        if session is None:
            return None

        utterances = self.utterances.list_for_session(session_id)
        assessments = self.assessments.list_for_session(session_id)
        by_utterance = {a.utterance_id: a for a in assessments if a.utterance_id}

        turns = []
        for utt in utterances:
            assessment = by_utterance.get(utt.utterance_id)
            detail = (
                self._utterance_feedback(utt.utterance_id)
                if utt.role == Role.LEARNER
                else {"corrections": [], "suggestions": [], "notes": []}
            )
            turns.append(
                {
                    "utterance_id": utt.utterance_id,
                    "role": utt.role,
                    "transcript": utt.transcript,
                    "created_at": utt.created_at,
                    "stt_confidence": utt.stt_confidence,
                    "overall": (
                        round(assessment.overall, 1)
                        if assessment and assessment.overall is not None
                        else None
                    ),
                    "scores": (
                        {
                            d: getattr(assessment, d)
                            for d in DIMENSIONS
                            if getattr(assessment, d) is not None
                        }
                        if assessment
                        else {}
                    ),
                    **detail,
                }
            )

        scores = _mean_scores(assessments)
        learner_turns = [t for t in turns if t["role"] == Role.LEARNER]
        return {
            "session_id": session_id,
            "user_id": session.user_id,
            "mode": session.mode,
            "started_at": session.started_at,
            "ended_at": session.ended_at,
            "duration_s": _duration_s(session.started_at, session.ended_at),
            "turns": turns,
            "learner_turns": len(learner_turns),
            "words_spoken": sum(
                len((t["transcript"] or "").split()) for t in learner_turns
            ),
            "assessments": len(assessments),
            "overall": _avg([a.overall for a in assessments if a.overall is not None]),
            "scores": scores,
            "strengths": _top(scores, best=True),
            "weaknesses": _top(scores, best=False),
            "corrections": [c for t in turns for c in t["corrections"]],
            "suggestions": sorted({s for t in turns for s in t["suggestions"]}),
            "recommendations": self._recommendations(scores),
            # Scoring is deferred under guard pressure, so "no scores yet" is a
            # normal state the UI has to be able to say out loud.
            "pending_scoring": len(learner_turns) > len(assessments),
        }

    def _utterance_feedback(self, utterance_id: str) -> dict:
        """Corrections and notes recovered from the stored evaluator payloads."""
        corrections: list[dict] = []
        suggestions: list[str] = []
        notes: list[str] = []
        for out in self.evaluator_outputs.list_for_utterance(utterance_id):
            try:
                payload = json.loads(out.payload_json)
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            # The LLM evaluator nests one node per dimension; the deterministic
            # ones are flat. Walk both rather than assuming a shape.
            for node in list(payload.values()) + [payload]:
                if not isinstance(node, dict):
                    continue
                for err in node.get("errors") or []:
                    if isinstance(err, dict) and err.get("correction"):
                        corrections.append(
                            {
                                "text": err.get("text"),
                                "correction": err.get("correction"),
                                "type": err.get("type"),
                            }
                        )
                for sug in node.get("suggestions") or []:
                    if isinstance(sug, str):
                        suggestions.append(sug)
            if payload.get("hesitations"):
                notes.append(f"{payload['hesitations']} hesitation(s)")
            if payload.get("self_corrections"):
                notes.append(f"{payload['self_corrections']} self-correction(s)")
        return {"corrections": corrections, "suggestions": suggestions, "notes": notes}

    def _recommendations(self, scores: dict[str, float]) -> list[dict]:
        """Two concrete actions for the weakest dimensions, worst first."""
        ranked = sorted(scores.items(), key=lambda kv: kv[1])
        out = []
        for dim, score in ranked[:3]:
            if score >= _STRONG:
                continue
            tips = _TIPS.get(dim)
            if not tips:
                continue
            out.append(
                {
                    "skill": dim,
                    "score": score,
                    "priority": "high" if score < _WEAK else "medium",
                    "actions": list(tips),
                }
            )
        return out

    # --- every conversation ------------------------------------------------

    def list_for_user(self, user_id: str, limit: int = 100) -> list[dict]:
        """One row per conversation: enough to choose which to open."""
        rows = []
        for session in self.sessions.list_for_user(user_id, limit=limit):
            # Read-aloud sessions belong to the Reading tab: they carry no coach
            # turn, and counting them here would dilute conversation averages
            # with a different exercise.
            if session.mode == SessionMode.READING:
                continue
            assessments = self.assessments.list_for_session(session.session_id)
            utterances = self.utterances.list_for_session(session.session_id)
            learner = [u for u in utterances if u.role == Role.LEARNER]
            first = next((u.transcript for u in learner if u.transcript), None)
            rows.append(
                {
                    "session_id": session.session_id,
                    "started_at": session.started_at,
                    "ended_at": session.ended_at,
                    "duration_s": _duration_s(session.started_at, session.ended_at),
                    "mode": session.mode,
                    "learner_turns": len(learner),
                    "assessments": len(assessments),
                    "overall": _avg([a.overall for a in assessments if a.overall is not None]),
                    "scores": _mean_scores(assessments),
                    "preview": (first[:120] if first else None),
                }
            )
        return rows

    def activity(self, user_id: str, *, days: int = 365) -> dict:
        """One cell per calendar day, GitHub-contributions style.

        Every day in the window is present, including empty ones — a heatmap
        with gaps omitted would silently compress time and draw a streak that
        never happened.
        """
        today = datetime.now(UTC).date()
        start = today - timedelta(days=days - 1)
        counts: dict[str, int] = {}
        seconds: dict[str, float] = {}

        for session in self.sessions.list_for_user(user_id, limit=10_000):
            try:
                day = datetime.fromisoformat(session.started_at).date()
            except ValueError:
                continue
            if day < start or day > today:
                continue
            key = day.isoformat()
            counts[key] = counts.get(key, 0) + 1
            dur = _duration_s(session.started_at, session.ended_at)
            if dur:
                seconds[key] = seconds.get(key, 0.0) + dur

        cells = []
        for offset in range(days):
            day = start + timedelta(days=offset)
            key = day.isoformat()
            cells.append(
                {
                    "date": key,
                    "weekday": day.weekday(),  # 0 = Monday, for column layout
                    "count": counts.get(key, 0),
                    "seconds": round(seconds.get(key, 0.0), 1),
                }
            )

        active = [c for c in cells if c["count"]]
        # Longest run anywhere in the window, as distinct from the *current*
        # streak the profile carries — a personal best you can lose is a
        # different number from the one you are holding.
        longest = current = 0
        for cell in cells:
            current = current + 1 if cell["count"] else 0
            longest = max(longest, current)

        return {
            "user_id": user_id,
            "from": start.isoformat(),
            "to": today.isoformat(),
            "days": days,
            "cells": cells,
            "active_days": len(active),
            "total_sessions": sum(c["count"] for c in cells),
            "total_seconds": round(sum(c["seconds"] for c in cells), 1),
            "busiest_day": max(active, key=lambda c: c["count"], default=None),
            "longest_streak": longest,
        }

    def history(self, user_id: str, *, limit: int = 500) -> list[dict]:
        """Every turn the learner and coach exchanged, newest conversation first.

        The Conversations view answers "how did that session go"; this answers
        "what have we actually talked about", which is a different question and
        wants a flat, scannable list.
        """
        out: list[dict] = []
        for session in self.sessions.list_for_user(user_id, limit=200):
            if session.mode == SessionMode.READING:
                continue
            turns = self.utterances.list_for_session(session.session_id)
            if not turns:
                continue
            out.append(
                {
                    "session_id": session.session_id,
                    "started_at": session.started_at,
                    "messages": [
                        {
                            "role": t.role,
                            "transcript": t.transcript,
                            "created_at": t.created_at,
                        }
                        for t in turns
                    ],
                }
            )
            if sum(len(c["messages"]) for c in out) >= limit:
                break
        return out

    def analyze_all(self, user_id: str, limit: int = 200) -> dict:
        """The across-conversations view: totals, averages, trend, what to fix.

        Built from the same per-conversation rows the list view uses, so the two
        can never disagree about a learner's numbers.
        """
        conversations = self.list_for_user(user_id, limit=limit)
        scored = [c for c in conversations if c["overall"] is not None]
        per_dim: dict[str, list[float]] = {}
        for c in conversations:
            for dim, val in c["scores"].items():
                per_dim.setdefault(dim, []).append(val)
        scores = {d: _avg(v) for d, v in per_dim.items() if _avg(v) is not None}

        # Oldest-first halves: "improving" should mean measured, not asserted.
        chronological = sorted(scored, key=lambda c: c["started_at"])
        half = len(chronological) // 2
        first_half = _avg([c["overall"] for c in chronological[:half]]) if half else None
        second_half = _avg([c["overall"] for c in chronological[half:]]) if half else None
        delta = (
            round(second_half - first_half, 1)
            if first_half is not None and second_half is not None
            else None
        )

        return {
            "user_id": user_id,
            "conversations": len(conversations),
            "scored_conversations": len(scored),
            "learner_turns": sum(c["learner_turns"] for c in conversations),
            "practice_seconds": round(
                sum(c["duration_s"] or 0 for c in conversations), 1
            ),
            "overall": _avg([c["overall"] for c in scored]),
            "best_conversation": max(scored, key=lambda c: c["overall"], default=None),
            "scores": scores,
            "strengths": _top(scores, best=True),
            "weaknesses": _top(scores, best=False),
            "trend": {
                "first_half_overall": first_half,
                "second_half_overall": second_half,
                "delta": delta,
                "direction": (
                    "improving"
                    if delta and delta > 1
                    else "declining"
                    if delta and delta < -1
                    else "steady"
                )
                if delta is not None
                else "not enough data",
            },
            "recommendations": self._recommendations(scores),
            "history": [
                {"started_at": c["started_at"], "overall": c["overall"]} for c in chronological
            ],
        }
