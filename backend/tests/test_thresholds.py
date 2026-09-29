"""
test_thresholds.py — Phase 3 critical path: asymmetric dual-threshold forgery detection.

Proves, without any AI/ML, that:
  * The configuration invariant 0 <= e_h < s_a < s_v < e_f <= 0.5 is enforced.
  * Any mismatch rate >= s_a aborts with ABORT_FORGERY (VERIFIED_ONLY or REJECTED tier).
  * The decision is an exact integer comparison (no float-boundary surprises).
  * Security bounds are mathematically consistent (exact <= Hoeffding <= epsilon).
  * End-to-end through Qiskit: honest signatures pass, blind forgeries are rejected.

Run from backend/:  pytest tests/ -v
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from watchdog.attack_simulation_harness import AttackType, ChannelSettings, calibrate_thresholds, simulate_attack
from watchdog.thresholds import (
    FORGER_MISMATCH_FLOOR_CLONING,
    DualThresholds,
    ForgeryException,
    MismatchVerdict,
    ThresholdConfigurationError,
    classify_mismatch,
    compute_mismatch_count,
    derive_dual_thresholds,
    enforce_forgery_bounds,
    enforce_forgery_bounds_from_rate,
    minimum_key_length,
    mismatch_distribution_curve,
)


@pytest.fixture
def testing_md_thresholds() -> DualThresholds:
    """The exact values from testing.md Test 3.3."""
    return DualThresholds(s_a=0.05, s_v=0.08, key_length=100)


# ---------------------------------------------------------------------------
# Test 3.3 — Forgery
# ---------------------------------------------------------------------------


def test_testing_md_case_3_3_mismatch_0_07_raises_forgery(testing_md_thresholds: DualThresholds) -> None:
    with pytest.raises(ForgeryException) as caught:
        enforce_forgery_bounds_from_rate(0.07, testing_md_thresholds)
    assert caught.value.abort_status == "ABORT_FORGERY"
    assert caught.value.assessment.verdict is MismatchVerdict.VERIFIED_ONLY
    assert caught.value.to_payload()["error"] == "ABORT_FORGERY"


def test_mismatch_below_s_a_is_authenticated(testing_md_thresholds: DualThresholds) -> None:
    assessment = enforce_forgery_bounds(4, 100, testing_md_thresholds)
    assert assessment.is_authenticated and assessment.verdict is MismatchVerdict.AUTHENTICATED


@pytest.mark.parametrize(
    ("mismatch_count", "expected_verdict"),
    [(5, MismatchVerdict.VERIFIED_ONLY), (7, MismatchVerdict.VERIFIED_ONLY),
     (8, MismatchVerdict.REJECTED), (50, MismatchVerdict.REJECTED), (100, MismatchVerdict.REJECTED)],
)
def test_every_mismatch_at_or_above_s_a_aborts(
    testing_md_thresholds: DualThresholds, mismatch_count: int, expected_verdict: MismatchVerdict
) -> None:
    with pytest.raises(ForgeryException) as caught:
        enforce_forgery_bounds(mismatch_count, 100, testing_md_thresholds)
    assert caught.value.assessment.verdict is expected_verdict


def test_boundaries_are_exact_integer_comparisons(testing_md_thresholds: DualThresholds) -> None:
    # 0.05 * 100 is 5.000000000000001 in floating point; the limit must still be 5.
    assert testing_md_thresholds.authentication_count_limit == 5
    assert testing_md_thresholds.verification_count_limit == 8


def test_verdict_partition_is_complete_and_monotone() -> None:
    thresholds = derive_dual_thresholds(4096, honest_error_rate=0.03)
    verdicts = [classify_mismatch(k, 4096, thresholds).verdict for k in range(4097)]
    order = [MismatchVerdict.AUTHENTICATED, MismatchVerdict.VERIFIED_ONLY, MismatchVerdict.REJECTED]
    ranks = [order.index(v) for v in verdicts]
    assert ranks == sorted(ranks)                        # never goes back to a lower tier
    assert ranks.index(1) == thresholds.authentication_count_limit
    assert ranks.index(2) == thresholds.verification_count_limit


# ---------------------------------------------------------------------------
# Configuration invariant: 0 <= e_h < s_a < s_v < e_f <= 0.5
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"s_a": 0.08, "s_v": 0.05, "key_length": 100},                              # s_a > s_v
        {"s_a": 0.05, "s_v": 0.05, "key_length": 100},                              # s_a == s_v
        {"s_a": 0.10, "s_v": 0.50, "key_length": 100},                              # s_v == 0.5
        {"s_a": 0.10, "s_v": 0.60, "key_length": 100},                              # s_v > 0.5
        {"s_a": 0.05, "s_v": 0.08, "key_length": 100, "honest_error_rate": 0.06},   # e_h > s_a
        {"s_a": 0.05, "s_v": 0.08, "key_length": 100, "forger_mismatch_floor": 0.07},  # e_f < s_v
        {"s_a": 0.05, "s_v": 0.08, "key_length": 0},                                # empty key
        {"s_a": float("nan"), "s_v": 0.08, "key_length": 100},
    ],
)
def test_invalid_threshold_configurations_are_rejected(kwargs: dict) -> None:
    with pytest.raises(ThresholdConfigurationError):
        DualThresholds(**kwargs)


def test_derived_thresholds_split_the_gap_in_thirds() -> None:
    thresholds = derive_dual_thresholds(4096, honest_error_rate=0.03)
    gap = FORGER_MISMATCH_FLOOR_CLONING - 0.03
    assert thresholds.s_a == pytest.approx(0.03 + gap / 3)
    assert thresholds.s_v == pytest.approx(0.03 + 2 * gap / 3)
    assert 0.03 < thresholds.s_a < thresholds.s_v < FORGER_MISMATCH_FLOOR_CLONING < 0.5


def test_channel_noisier_than_forger_floor_is_refused() -> None:
    with pytest.raises(ThresholdConfigurationError):
        derive_dual_thresholds(4096, honest_error_rate=0.2)


def test_key_length_mismatch_is_refused(testing_md_thresholds: DualThresholds) -> None:
    with pytest.raises(ThresholdConfigurationError):
        classify_mismatch(3, 99, testing_md_thresholds)


# ---------------------------------------------------------------------------
# Security bounds (Chernoff-Hoeffding and exact binomial)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key_length", [256, 1024, 4096])
def test_exact_tails_never_exceed_hoeffding(key_length: int) -> None:
    bounds = derive_dual_thresholds(key_length, honest_error_rate=0.0294).security_bounds()
    assert 0 <= bounds.honest_abort_exact <= bounds.honest_abort_hoeffding <= 1
    assert 0 <= bounds.forgery_acceptance_exact <= bounds.forgery_acceptance_hoeffding <= 1


def test_bounds_shrink_as_key_length_grows() -> None:
    short = derive_dual_thresholds(1024, 0.0294).security_bounds()
    long = derive_dual_thresholds(4096, 0.0294).security_bounds()
    assert long.forgery_acceptance_exact < short.forgery_acceptance_exact
    assert long.repudiation_hoeffding < short.repudiation_hoeffding


@pytest.mark.parametrize("epsilon", [1e-3, 1e-6, 1e-9])
def test_minimum_key_length_meets_epsilon_for_all_three_bounds(epsilon: float) -> None:
    length = minimum_key_length(0.0294, epsilon)
    bounds = derive_dual_thresholds(length, 0.0294).security_bounds()
    assert bounds.honest_abort_hoeffding <= epsilon
    assert bounds.forgery_acceptance_hoeffding <= epsilon
    assert bounds.repudiation_hoeffding <= epsilon


# ---------------------------------------------------------------------------
# Mismatch counting and visualizer data
# ---------------------------------------------------------------------------


def test_mismatch_count_is_elementwise_disagreement() -> None:
    assert compute_mismatch_count([0, 1, 1, 0, 1], [0, 0, 1, 1, 1]) == 2
    with pytest.raises(ValueError):
        compute_mismatch_count([0, 1], [0, 1, 1])


@pytest.mark.parametrize("probability", [0.03, 0.1667, 0.5])
def test_distribution_curve_is_a_probability_distribution(probability: float) -> None:
    curve = mismatch_distribution_curve(4096, probability)
    total = sum(point["probability"] for point in curve)
    mean = sum(point["mismatch_rate"] * point["probability"] for point in curve)
    assert total == pytest.approx(1.0, abs=1e-6)
    assert mean == pytest.approx(probability, abs=1e-6)


# ---------------------------------------------------------------------------
# End-to-end through the Qiskit engine
# ---------------------------------------------------------------------------

SETTINGS = ChannelSettings()   # L = 4096, p = 0.02, 100 km


@pytest.mark.parametrize("seed", range(10))
def test_honest_signatures_are_authenticated(seed: int) -> None:
    telemetry = simulate_attack(AttackType.NONE, SETTINGS, physics_seed=seed)
    assessment = enforce_forgery_bounds(telemetry.mismatch_count, telemetry.key_length, telemetry.thresholds)
    assert assessment.is_authenticated
    assert telemetry.mismatch_rate < telemetry.thresholds.s_a


@pytest.mark.parametrize("seed", range(10))
def test_blind_forgery_crosses_s_v_and_is_rejected(seed: int) -> None:
    telemetry = simulate_attack(AttackType.FORGERY, SETTINGS, physics_seed=seed)
    assert telemetry.mismatch_rate > telemetry.thresholds.s_v
    with pytest.raises(ForgeryException) as caught:
        enforce_forgery_bounds(telemetry.mismatch_count, telemetry.key_length, telemetry.thresholds)
    assert caught.value.assessment.verdict is MismatchVerdict.REJECTED


def test_forgery_leaves_the_quantum_channel_untouched() -> None:
    """Forgery is caught by the mismatch rule, not by fidelity (so it is labelled correctly)."""
    honest = simulate_attack(AttackType.NONE, SETTINGS, physics_seed=0)
    forged = simulate_attack(AttackType.FORGERY, SETTINGS, physics_seed=0)
    assert forged.batch_state_fidelity == pytest.approx(honest.batch_state_fidelity, abs=1e-3)
    assert forged.batch_state_fidelity > 0.6667


def test_calibrated_thresholds_match_channel_fidelity() -> None:
    thresholds = calibrate_thresholds(SETTINGS)
    assert thresholds.key_length == 4096
    assert math.isclose(thresholds.honest_error_rate, 1 - 0.9706, abs_tol=5e-4)
    assert 0 < thresholds.s_a < thresholds.s_v < 0.5
    assert np.isfinite(thresholds.security_bounds().forgery_acceptance_exact)
