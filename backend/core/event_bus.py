"""In-process asyncio pub/sub — the seam between the two paths.

Right-sized for one host: no Kafka, no broker. ``publish`` is **non-blocking** —
it schedules each subscriber as a background task and returns immediately, so the
hot path never waits on cold-path work. Subscribers must be non-blocking and
idempotent (cold jobs may be retried after a guard deferral).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from backend.core.logging import get_logger

log = get_logger("event_bus")

Handler = Callable[[Any], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[type, list[Handler]] = defaultdict(list)
        self._tasks: set[asyncio.Task] = set()

    def subscribe(self, event_type: type, handler: Handler) -> None:
        self._subs[event_type].append(handler)

    def publish(self, event: Any) -> list[asyncio.Task]:
        """Schedule all subscribers for ``type(event)``. Returns their tasks so a
        caller (or a test) may await completion; the hot path just ignores them."""
        tasks: list[asyncio.Task] = []
        for handler in self._subs.get(type(event), []):
            task = asyncio.create_task(self._run(handler, event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            tasks.append(task)
        return tasks

    async def _run(self, handler: Handler, event: Any) -> None:
        try:
            await handler(event)
        except Exception as exc:  # noqa: BLE001 — one bad subscriber must not kill others
            log.error(
                "event_handler_failed",
                event=type(event).__name__,
                handler=getattr(handler, "__name__", repr(handler)),
                error=str(exc),
            )

    async def drain(self) -> None:
        """Await all in-flight handler tasks (shutdown / test synchronization)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    @property
    def pending(self) -> int:
        return len(self._tasks)
