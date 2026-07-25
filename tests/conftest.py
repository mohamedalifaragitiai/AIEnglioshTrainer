"""Shared test fixtures."""

from __future__ import annotations

import os
import pathlib
import tempfile

# Point the app's SQLite store at a fresh temp file BEFORE backend.main is imported
# by any test module, so API tests never touch the real repo data dir.
_TEST_DB_DIR = pathlib.Path(tempfile.gettempdir()) / "english_coach_tests"
_TEST_DB_DIR.mkdir(exist_ok=True)
_TEST_DB = _TEST_DB_DIR / "api.db"
for _suffix in ("", "-wal", "-shm"):
    _p = pathlib.Path(str(_TEST_DB) + _suffix)
    if _p.exists():
        _p.unlink()
os.environ["COACH_DB_PATH"] = str(_TEST_DB)
os.environ["COACH_REPORT_DIR"] = str(_TEST_DB_DIR / "reports")
# Isolate tests from any local .env used for a live runtime (env vars win over .env):
# never load real models, keep the LLM server unreachable, use the default VRAM budget.
os.environ["COACH_LOAD_MODELS"] = "false"
os.environ["COACH_VLLM_BASE_URL"] = "http://127.0.0.1:59999"
os.environ["COACH_VLLM_VRAM_FRACTION"] = "0.68"

import pytest  # noqa: E402

from backend.core.resource_guard import ResourceGuard, ResourceSnapshot  # noqa: E402
from backend.persistence.db import Database  # noqa: E402
from backend.persistence.migrations import migrate  # noqa: E402
from backend.persistence.progress import ProgressService  # noqa: E402
from backend.persistence.repositories import (  # noqa: E402
    AssessmentRepository,
    EvaluatorOutputRepository,
    GapSnapshotRepository,
    SessionRepository,
    UserRepository,
    UtteranceRepository,
)
from config.settings import Settings  # noqa: E402


class FakeSampler:
    """A sampler with settable readings — no hardware required."""

    vram_total_bytes = 16 * 10**9
    ram_total_bytes = 64 * 10**9

    def __init__(self, gpu: bool = True) -> None:
        self.gpu = gpu
        self.ratios: dict[str, float | None] = {
            "vram": 0.30 if gpu else None,
            "gpu_util": 0.20 if gpu else None,
            "ram": 0.30,
            "cpu": 0.10,
            "disk": 0.40,
        }
        if not gpu:
            self.vram_total_bytes = None

    def sample(self) -> ResourceSnapshot:
        return ResourceSnapshot(ratios=dict(self.ratios))


@pytest.fixture
def settings() -> Settings:
    # Deterministic defaults matching the reference spec.
    return Settings(
        resource_ceiling=0.96,
        resource_soft=0.88,
        rolling_window=3,
        hysteresis_margin=0.06,
        ladder_l1=0.88,
        ladder_l2=0.92,
        ladder_l3=0.94,
        ladder_l4=0.96,
    )


@pytest.fixture
def sampler() -> FakeSampler:
    return FakeSampler()


@pytest.fixture
def guard(sampler: FakeSampler, settings: Settings) -> ResourceGuard:
    return ResourceGuard(sampler=sampler, settings=settings)


def feed_steady(guard: ResourceGuard, sampler: FakeSampler, vram: float) -> None:
    """Drive the guard to a steady VRAM reading.

    Clears the rolling window first so the smoothed value equals `vram` with no
    residue from a prior reading — the hysteresis memory lives in the guard's
    degradation *level*, not in the window (the window only suppresses spikes).
    This makes level transitions depend cleanly on (current level, new value).
    """
    guard._window.clear()
    sampler.ratios["vram"] = vram
    for _ in range(guard._window.maxlen or 3):
        guard.feed(sampler.sample())


# --- persistence fixtures --------------------------------------------------


@pytest.fixture
def db(tmp_path) -> Database:
    """A migrated, isolated SQLite database (WAL) per test."""
    database = Database(tmp_path / "coach.db")
    migrate(database)
    return database


@pytest.fixture
def users(db: Database) -> UserRepository:
    return UserRepository(db)


@pytest.fixture
def sessions(db: Database) -> SessionRepository:
    return SessionRepository(db)


@pytest.fixture
def utterances(db: Database) -> UtteranceRepository:
    return UtteranceRepository(db)


@pytest.fixture
def assessments(db: Database) -> AssessmentRepository:
    return AssessmentRepository(db)


@pytest.fixture
def evaluator_outputs(db: Database) -> EvaluatorOutputRepository:
    return EvaluatorOutputRepository(db)


@pytest.fixture
def gaps(db: Database) -> GapSnapshotRepository:
    return GapSnapshotRepository(db)


@pytest.fixture
def progress(
    users: UserRepository,
    sessions: SessionRepository,
    assessments: AssessmentRepository,
) -> ProgressService:
    return ProgressService(users, sessions, assessments)
