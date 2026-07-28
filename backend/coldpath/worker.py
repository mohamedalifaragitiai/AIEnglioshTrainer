"""Cold-path worker — consumes UtteranceFinalized, evaluates, scores, updates.

Subscribes to the event bus and runs enabled evaluators, aggregates their outputs
into a versioned Assessment, updates the profile, and emits AssessmentReady. Every
job is **deferrable**: under guard pressure the guard returns ``defer`` and the job
is re-queued with jittered backoff, draining when headroom returns. Jobs are
**idempotent** — an utterance already scored is skipped — so retries are safe.
A job carries the time it first entered the queue, so the guard can tell a job that
just arrived from one that has been going round the re-queue loop; past
``coldpath_max_defer_s`` the guard admits it rather than deferring forever.

``process_once`` runs one job deterministically (used directly by tests); the
background loop just pumps the queue and honors deferrals.
"""

from __future__ import annotations

import asyncio
import random
from time import monotonic, perf_counter

from backend.coldpath.evaluators.base import (
    EvaluationContext,
    Evaluator,
    UtteranceForEval,
)
from backend.coldpath.scoring_service import ScoringService
from backend.core import metrics
from backend.core.event_bus import EventBus
from backend.core.logging import get_logger
from backend.core.resource_guard import ResourceEstimate, ResourceGuard
from backend.domain.events import AssessmentReady, UtteranceFinalized
from backend.domain.models import Role
from backend.persistence.repositories import (
    AssessmentRepository,
    SessionRepository,
    UserRepository,
    UtteranceRepository,
)

log = get_logger("coldpath")


class ColdPathWorker:
    def __init__(
        self,
        *,
        guard: ResourceGuard,
        evaluators: list[Evaluator],
        scoring: ScoringService,
        users: UserRepository,
        sessions: SessionRepository,
        utterances: UtteranceRepository,
        assessments: AssessmentRepository,
        event_bus: EventBus | None = None,
        backoff_s: float = 1.0,
    ):
        self.guard = guard
        self.evaluators = evaluators
        self.scoring = scoring
        self.users = users
        self.sessions = sessions
        self.utterances = utterances
        self.assessments = assessments
        self.bus = event_bus
        self.backoff_s = backoff_s
        # (event, monotonic time it first entered the queue) — the second element
        # survives re-queues so a starved job can be told apart from a fresh one.
        self._queue: asyncio.Queue[tuple[UtteranceFinalized, float]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    # --- wiring / lifecycle ------------------------------------------------

    def attach(self, bus: EventBus) -> None:
        self.bus = self.bus or bus
        bus.subscribe(UtteranceFinalized, self._enqueue)

    async def _enqueue(self, ev: UtteranceFinalized, first_seen: float | None = None) -> None:
        self._queue.put_nowait((ev, monotonic() if first_seen is None else first_seen))
        metrics.coldpath_queue_depth.set(self._queue.qsize())

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="coldpath-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                ev, first_seen = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except TimeoutError:
                continue
            metrics.coldpath_queue_depth.set(self._queue.qsize())
            status = await self.process_once(ev, waited_s=monotonic() - first_seen)
            if status == "deferred":
                # Back off with jitter, then re-queue — cold work is deferrable.
                # Keep the ORIGINAL first_seen: the wait has to accumulate across
                # re-queues, otherwise the deferral budget resets every lap and the
                # job never ages out of the loop.
                await asyncio.sleep(self.backoff_s * (1.0 + random.random()))
                await self._enqueue(ev, first_seen)

    # --- one job -----------------------------------------------------------

    async def process_once(self, ev: UtteranceFinalized, waited_s: float = 0.0) -> str:
        if self.assessments.exists_for_utterance(ev.utterance_id):
            metrics.coldpath_jobs_total.labels("skipped").inc()
            return "skipped"

        adm = await self.guard.acquire(
            ResourceEstimate(gpu_util_frac=0.4, vram_gb=0.0, waited_s=waited_s), "cold"
        )
        if adm.kind == "defer":
            metrics.coldpath_jobs_total.labels("deferred").inc()
            return "deferred"

        try:
            await self._evaluate_and_store(ev)
        except Exception as exc:  # noqa: BLE001 — one bad job must not kill the worker
            metrics.coldpath_jobs_total.labels("error").inc()
            log.error("coldpath_job_failed", utterance_id=ev.utterance_id, error=str(exc))
            return "error"
        metrics.coldpath_jobs_total.labels("processed").inc()
        return "processed"

    async def _evaluate_and_store(self, ev: UtteranceFinalized) -> None:
        utt = UtteranceForEval(
            utterance_id=ev.utterance_id,
            session_id=ev.session_id,
            user_id=ev.user_id,
            transcript=ev.transcript,
            audio_path=ev.audio_path,
            stt_confidence=ev.stt_confidence,
            start_ms=ev.start_ms,
            end_ms=ev.end_ms,
        )
        ctx = self._build_context(ev)

        outputs = []
        for evaluator in self.evaluators:
            if not evaluator.available():
                continue
            t0 = perf_counter()
            try:
                out = await evaluator.evaluate(utt, ctx)
            except Exception as exc:  # noqa: BLE001 — skip a failed evaluator, keep the rest
                log.warning("evaluator_failed", evaluator=evaluator.name, error=str(exc))
                continue
            metrics.evaluator_duration_seconds.labels(evaluator.name).observe(
                perf_counter() - t0
            )
            outputs.append(out)

        assessment = self.scoring.record(utt, outputs)
        metrics.assessments_produced_total.inc()
        log.info(
            "assessment_ready",
            user_id=ev.user_id,
            assessment_id=assessment.assessment_id,
            overall=assessment.overall,
            evaluators=[o.evaluator for o in outputs],
        )
        if self.bus is not None:
            self.bus.publish(
                AssessmentReady(
                    user_id=ev.user_id,
                    session_id=ev.session_id,
                    assessment_id=assessment.assessment_id,
                )
            )

    def _build_context(self, ev: UtteranceFinalized) -> EvaluationContext:
        """Coach's last prompt + recent turns for the session, learner level."""
        prompt: str | None = None
        recent: list[dict] = []
        try:
            turns = self.utterances.list_for_session(ev.session_id)
            for t in turns:
                role = "assistant" if str(t.role) == Role.COACH else "user"
                if t.transcript:
                    recent.append({"role": role, "content": t.transcript})
                if str(t.role) == Role.COACH:
                    prompt = t.transcript
        except Exception as exc:  # noqa: BLE001
            log.warning("context_build_failed", error=str(exc))
        level = 0
        user = self.users.get(ev.user_id)
        if user is not None:
            level = user.current_level
        return EvaluationContext(
            prompt=prompt,
            recent_turns=recent[-8:],
            learner_level=level,
            scoring_model_version=self.scoring.version,
        )
