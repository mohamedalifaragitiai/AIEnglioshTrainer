"""Structured logging (structlog) with per-session correlation ids.

Every component logs JSON with a shared ``correlation_id`` so a single learner
turn — or a single guard degradation event — can be traced across hot and cold
paths. ``configure_logging`` is idempotent and safe to call at app startup and in
tests.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

import structlog

# Correlation id carried across async tasks within a request/session.
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_configured = False


def bind_correlation_id(value: str | None) -> None:
    """Set the correlation id for the current async context."""
    _correlation_id.set(value)


def _inject_correlation_id(_logger, _method, event_dict):
    cid = _correlation_id.get()
    if cid is not None:
        event_dict.setdefault("correlation_id", cid)
    return event_dict


def configure_logging(*, level: str = "INFO", json_logs: bool = True) -> None:
    """Configure structlog once. Subsequent calls are no-ops unless forced."""
    global _configured
    if _configured:
        return

    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )

    renderer = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _inject_correlation_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str | None = None):
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
