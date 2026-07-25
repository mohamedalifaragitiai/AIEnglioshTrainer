"""Prometheus collectors.

Everything observable: if it runs, it emits metrics. Phase 0 defines the
ResourceGuard's metrics (usage ratios, ceiling hits, degradation level, deferrals,
sampler cost). Later phases add hot-path stage latencies and evaluator durations.

All collectors register against a single module-level ``REGISTRY`` so importing
this module twice (e.g. under pytest) does not raise duplicate-timeseries errors.
Use :func:`render_metrics` to produce the ``/metrics`` payload.
"""

from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.exposition import CONTENT_TYPE_LATEST

# Dedicated registry (not the process-global default) so tests and repeated
# imports stay isolated and deterministic.
REGISTRY = CollectorRegistry()

CONTENT_TYPE = CONTENT_TYPE_LATEST

# --- ResourceGuard metrics (see references/resource-governance.md) ----------

resource_usage_ratio = Gauge(
    "resource_usage_ratio",
    "Latest smoothed usage ratio per resource (0..1).",
    ["resource"],
    registry=REGISTRY,
)

resource_ceiling_hits_total = Counter(
    "resource_ceiling_hits_total",
    "Count of samples where a resource crossed the hard ceiling.",
    ["resource"],
    registry=REGISTRY,
)

degradation_level = Gauge(
    "degradation_level",
    "Current degradation ladder level (0 normal .. 4 severe).",
    registry=REGISTRY,
)

jobs_deferred_total = Counter(
    "jobs_deferred_total",
    "Cold-path jobs deferred by the guard under pressure.",
    registry=REGISTRY,
)

sessions_rejected_total = Counter(
    "sessions_rejected_total",
    "New sessions rejected by the guard at the ceiling.",
    registry=REGISTRY,
)

guard_sample_duration_seconds = Histogram(
    "guard_sample_duration_seconds",
    "Wall time to take one resource sample (proves the guard is cheap).",
    registry=REGISTRY,
    buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25),
)


# --- Model serving metrics (Phase 2) ----------------------------------------

model_loaded = Gauge(
    "model_loaded",
    "1 if a model is loaded/ready, 0 otherwise.",
    ["model", "kind"],
    registry=REGISTRY,
)

model_vram_estimate_gb = Gauge(
    "model_vram_estimate_gb",
    "Estimated resident VRAM for a model (GB).",
    ["model", "kind"],
    registry=REGISTRY,
)

model_load_duration_seconds = Histogram(
    "model_load_duration_seconds",
    "Wall time to load a model through the guard.",
    ["model", "kind"],
    registry=REGISTRY,
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

llm_request_duration_seconds = Histogram(
    "llm_request_duration_seconds",
    "Latency of an LLM chat request to the vLLM server.",
    ["model", "path"],
    registry=REGISTRY,
    buckets=(0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.0, 5.0, 10.0),
)


# --- Hot-path metrics (Phase 3) ---------------------------------------------

hotpath_stage_seconds = Histogram(
    "hotpath_stage_seconds",
    "Per-stage latency of a hot-path turn.",
    ["stage"],  # stt | llm | tts_first | tts_total
    registry=REGISTRY,
    buckets=(0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0, 2.0, 5.0),
)

hotpath_first_audio_seconds = Histogram(
    "hotpath_first_audio_seconds",
    "Time from finalized user speech to first TTS audio chunk (the <300ms budget).",
    registry=REGISTRY,
    buckets=(0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.6, 1.0, 2.0),
)

hotpath_turns_total = Counter(
    "hotpath_turns_total",
    "Completed hot-path turns by outcome.",
    ["outcome"],  # ok | degraded | error
    registry=REGISTRY,
)


def render_metrics() -> bytes:
    """Serialize the registry in Prometheus text exposition format."""
    return generate_latest(REGISTRY)
