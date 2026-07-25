"""Assemble the cold-path evaluators and worker from app components."""

from __future__ import annotations

from backend.coldpath.evaluators.base import Evaluator
from backend.coldpath.evaluators.confidence import ConfidenceEvaluator
from backend.coldpath.evaluators.fluency import FluencyEvaluator
from backend.coldpath.evaluators.llm_eval import LLMEvaluator
from backend.coldpath.pronunciation.evaluator import PronunciationEvaluator
from backend.coldpath.pronunciation.gop import GOPScorer
from backend.coldpath.scoring import SCORING_MODEL_VERSION
from backend.coldpath.scoring_service import ScoringService
from backend.coldpath.worker import ColdPathWorker
from backend.core.event_bus import EventBus
from backend.core.resource_guard import ResourceGuard
from backend.persistence.db import Database
from backend.persistence.repositories import (
    AssessmentRepository,
    EvaluatorOutputRepository,
    SessionRepository,
    UserRepository,
    UtteranceRepository,
)
from backend.serving.adapters import Wav2Vec2GOPModel
from backend.serving.llm_client import VLLMClient


def build_evaluators(
    llm_client: VLLMClient, gop_model: Wav2Vec2GOPModel | None
) -> list[Evaluator]:
    gop = GOPScorer(gop_model) if gop_model is not None else None
    return [
        LLMEvaluator(llm_client, version=SCORING_MODEL_VERSION),  # 5 dims, batched
        FluencyEvaluator(),
        ConfidenceEvaluator(),
        PronunciationEvaluator(gop),  # real GOP if resident + audio, else proxy
    ]


def build_worker(
    *,
    guard: ResourceGuard,
    llm_client: VLLMClient,
    gop_model: Wav2Vec2GOPModel | None,
    db: Database,
    event_bus: EventBus,
) -> ColdPathWorker:
    users = UserRepository(db)
    sessions = SessionRepository(db)
    utterances = UtteranceRepository(db)
    assessments = AssessmentRepository(db)
    scoring = ScoringService(assessments, EvaluatorOutputRepository(db), users)
    return ColdPathWorker(
        guard=guard,
        evaluators=build_evaluators(llm_client, gop_model),
        scoring=scoring,
        users=users,
        sessions=sessions,
        utterances=utterances,
        assessments=assessments,
        event_bus=event_bus,
    )
