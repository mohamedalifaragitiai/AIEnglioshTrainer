"""Small shared helpers: stable ids and UTC ISO timestamps."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4


def new_id(prefix: str = "") -> str:
    """A unique id, optionally prefixed for readability (e.g. ``sess_...``)."""
    raw = uuid4().hex
    return f"{prefix}_{raw}" if prefix else raw


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string (sortable, timezone-aware)."""
    return datetime.now(UTC).isoformat()


def today_utc() -> str:
    """Current UTC calendar date as ``YYYY-MM-DD`` (for streak day math)."""
    return datetime.now(UTC).date().isoformat()
