"""Tests for versioned scoring primitives."""

from __future__ import annotations

import pytest

from backend.coldpath.scoring import (
    DIMENSIONS,
    SCORING_MODEL_VERSION,
    ScoringModel,
    compute_overall,
    get_scoring_model,
    level_for_overall,
)


def test_weights_present_and_sum_to_one():
    model = get_scoring_model(SCORING_MODEL_VERSION)
    assert set(model.weights) == set(DIMENSIONS)
    assert abs(sum(model.weights.values()) - 1.0) < 1e-9


def test_overall_all_100_is_100():
    scores = dict.fromkeys(DIMENSIONS, 100.0)
    assert compute_overall(scores) == pytest.approx(100.0)


def test_overall_weighted_mix():
    # Only pronunciation (weight 0.20) at 100, rest 0 → overall 20.
    scores = dict.fromkeys(DIMENSIONS, 0.0)
    scores["pronunciation"] = 100.0
    assert compute_overall(scores) == pytest.approx(20.0)


@pytest.mark.parametrize(
    "overall,level",
    [(0, 0), (39, 0), (40, 1), (54, 1), (55, 2), (70, 3), (83, 4), (93, 4), (94, 5), (100, 5)],
)
def test_level_mapping(overall, level):
    assert level_for_overall(overall) == level


def test_unknown_version_raises():
    with pytest.raises(KeyError):
        get_scoring_model("v999")


def test_bad_weights_rejected():
    with pytest.raises(ValueError, match="sum to"):
        ScoringModel(
            version="bad",
            weights=dict.fromkeys(DIMENSIONS, 0.5),  # sums to 4.0
            level_thresholds=((100, 5),),
        )
