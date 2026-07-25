"""Tests for the in-process asyncio event bus."""

from __future__ import annotations

from dataclasses import dataclass

from backend.core.event_bus import EventBus


@dataclass(frozen=True)
class Ping:
    n: int


@dataclass(frozen=True)
class Other:
    pass


async def test_publish_dispatches_to_subscribers():
    bus = EventBus()
    seen = []
    bus.subscribe(Ping, lambda e: _append(seen, e.n))
    bus.publish(Ping(1))
    bus.publish(Ping(2))
    await bus.drain()
    assert sorted(seen) == [1, 2]


async def test_only_matching_type_dispatched():
    bus = EventBus()
    seen = []
    bus.subscribe(Ping, lambda e: _append(seen, e.n))
    bus.publish(Other())  # no Ping subscribers → nothing happens
    await bus.drain()
    assert seen == []


async def test_multiple_subscribers_all_run():
    bus = EventBus()
    a, b = [], []
    bus.subscribe(Ping, lambda e: _append(a, e.n))
    bus.subscribe(Ping, lambda e: _append(b, e.n))
    bus.publish(Ping(7))
    await bus.drain()
    assert a == [7] and b == [7]


async def test_one_failing_handler_does_not_kill_others():
    bus = EventBus()
    good = []

    async def boom(_e):
        raise RuntimeError("subscriber blew up")

    bus.subscribe(Ping, boom)
    bus.subscribe(Ping, lambda e: _append(good, e.n))
    bus.publish(Ping(5))
    await bus.drain()
    assert good == [5]  # the healthy subscriber still ran


async def test_publish_is_nonblocking_returns_tasks():
    bus = EventBus()
    bus.subscribe(Ping, lambda e: _append([], e.n))
    tasks = bus.publish(Ping(1))
    assert len(tasks) == 1
    await bus.drain()


async def _append(target, value):
    target.append(value)
