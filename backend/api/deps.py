"""FastAPI dependencies — build repositories/services from app state."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from backend.persistence.db import Database
from backend.persistence.progress import ProgressService
from backend.persistence.repositories import (
    AssessmentRepository,
    EvaluatorOutputRepository,
    GapSnapshotRepository,
    SessionRepository,
    UserRepository,
    UtteranceRepository,
)


@dataclass
class Repositories:
    users: UserRepository
    sessions: SessionRepository
    utterances: UtteranceRepository
    assessments: AssessmentRepository
    evaluator_outputs: EvaluatorOutputRepository
    gaps: GapSnapshotRepository

    @classmethod
    def build(cls, db: Database) -> Repositories:
        return cls(
            users=UserRepository(db),
            sessions=SessionRepository(db),
            utterances=UtteranceRepository(db),
            assessments=AssessmentRepository(db),
            evaluator_outputs=EvaluatorOutputRepository(db),
            gaps=GapSnapshotRepository(db),
        )


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_repos(request: Request) -> Repositories:
    return Repositories.build(request.app.state.db)


def get_progress(request: Request) -> ProgressService:
    repos = Repositories.build(request.app.state.db)
    return ProgressService(repos.users, repos.sessions, repos.assessments)
