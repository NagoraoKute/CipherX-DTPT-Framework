"""
test_fidelity.py — Phase 3 critical path: Replay & Eavesdropping detection.

Proves, without any AI/ML, that:
  * F <= 0.6667 aborts with ABORT_EAVESDROP (intercept-resend limit, 2/3).
  * F == 0.5 (+/- 0.01) aborts with ABORT_REPLAY, and replay is checked FIRST.
  * Batch averaging prevents an intercepted token (F = 0.5 alone) from being
    mislabelled as a replay.
  * The physics behind both numbers is reproduced by Qiskit itself.

Run from backend/:  pytest tests/ -v
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from qiskit.quantum_info import DensityMatrix

from quantum_engine.teleportation import VALID_BROADCASTS, PauliEigenstate, apply_pauli_correction
from watchdog.attack_simulation_harness import intercept_fidelity_table, replay_fidelity_table
from watchdog.fidelity import (
    CLASSICAL_TELEPORTATION_LIMIT,
    REPLAY_FIDELITY_TOLERANCE,
    EavesdroppingException,
    FidelityThreatException,
    FidelityVerdict,
    ReplayAttackException,
    classify_state_fidelity,
    compute_state_fidelity,
    enforce_fidelity_bounds,
    evaluate_batch_fidelity,
    mean_state_fidelity,
)

# ---------------------------------------------------------------------------
# Test 3.1 — Eavesdropping (intercept-resend): F <= 0.6667
# ---------------------------------------------------------------------------


def test_testing_md_case_3_1_fidelity_0_65_raises_eavesdropping() -> None:
    with pytest.raises(EavesdroppingException) as caught:
        enforce_fidelity_bounds(0.65)
    assert caught.value.abort_status == "ABORT_EAVESDROP"
    assert caught.value.state_fidelity == pytest.approx(0.65)


@pytest.mark.parametrize("fidelity", [0.0, 0.2, 0.48, 0.52, 0.6, 2 / 3, 0.66669, CLASSICAL_TELEPORTATION_LIMIT])
def test_every_fidelity_at_or_below_limit_outside_replay_band_is_eavesdropping(fidelity: float) -> None:
    with pytest.raises(EavesdroppingException):
        enforce_fidelity_bounds(fidelity)


def test_limit_is_inclusive_and_the_next_float_above_passes() -> None:
    with pytest.raises(EavesdroppingException):
        enforce_fidelity_bounds(0.6667)
    just_above = math.nextafter(CLASSICAL_TELEPORTATION_LIMIT, 1.0)
    assert enforce_fidelity_bounds(just_above).verdict is FidelityVerdict.SECURE


@pytest.mark.parametrize("fidelity", [0.6668, 0.8, 0.9706, 0.99, 1.0])
def test_fidelity_above_limit_is_secure(fidelity: float) -> None:
    assessment = enforce_fidelity_bounds(fidelity)
    assert assessment.is_secure
    assert assessment.margin_above_classical_limit > 0


# ---------------------------------------------------------------------------
# Test 3.2 — Replay: F == 0.5 (checked before eavesdropping)
# ---------------------------------------------------------------------------


def test_testing_md_case_3_2_fidelity_0_5_raises_replay() -> None:
    with pytest.raises(ReplayAttackException) as caught:
        enforce_fidelity_bounds(0.5000)
    assert caught.value.abort_status == "ABORT_REPLAY"


@pytest.mark.parametrize("fidelity", [0.49, 0.495, 0.4999999999999999, 0.5, 0.505, 0.51])
def test_replay_band_is_0_5_plus_minus_0_01(fidelity: float) -> None:
    with pytest.raises(ReplayAttackException):
        enforce_fidelity_bounds(fidelity)


def test_replay_takes_precedence_over_eavesdropping() -> None:
    """0.5 also satisfies F <= 0.6667, so the rule order is what makes it a replay."""
    assert 0.5 <= CLASSICAL_TELEPORTATION_LIMIT
    assert classify_state_fidelity(0.5).verdict is FidelityVerdict.REPLAY_ATTACK


def test_values_just_outside_replay_band_fall_through_to_eavesdropping() -> None:
    delta = REPLAY_FIDELITY_TOLERANCE + 1e-6
    for fidelity in (0.5 - delta, 0.5 + delta):
        assert classify_state_fidelity(fidelity).verdict is FidelityVerdict.EAVESDROPPING


def test_both_exceptions_share_the_base_class_caught_by_the_api() -> None:
    assert issubclass(ReplayAttackException, FidelityThreatException)
    assert issubclass(EavesdroppingException, FidelityThreatException)
    with pytest.raises(FidelityThreatException) as caught:
        enforce_fidelity_bounds(0.5)
    assert caught.value.to_payload()["error"] == "ABORT_REPLAY"


# ---------------------------------------------------------------------------
# Physics: Qiskit reproduces 0.5 and 2/3
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("broadcast", VALID_BROADCASTS)
@pytest.mark.parametrize("token", list(PauliEigenstate))
def test_replayed_correction_on_unentangled_qubit_gives_exactly_half(token: PauliEigenstate, broadcast: str) -> None:
    maximally_mixed = DensityMatrix(np.eye(2) / 2)
    fidelity = compute_state_fidelity(apply_pauli_correction(maximally_mixed, broadcast), token.statevector)
    assert fidelity == pytest.approx(0.5, abs=1e-12)


def test_qiskit_replay_circuit_average_fidelity_is_half() -> None:
    table = replay_fidelity_table(0.0, 0.0)   # (4 broadcasts, 6 eigenstates)
    assert np.allclose(table, 0.5, atol=1e-12)


def test_qiskit_intercept_resend_average_fidelity_is_two_thirds() -> None:
    """Noiseless measure-and-resend over Eve's 3 bases: (1 + 0.5 + 0.5) / 3 = 2/3 for every token."""
    table = intercept_fidelity_table(0.0, 0.0)   # (6 tokens, 3 Eve bases, 6 eigenstates)
    per_token_average = np.array([table[i, :, i].mean() for i in range(len(PauliEigenstate))])
    assert np.allclose(per_token_average, 2 / 3, atol=1e-12)
    assert np.all(per_token_average <= CLASSICAL_TELEPORTATION_LIMIT)


# ---------------------------------------------------------------------------
# Batch evaluation (prevents per-token mislabelling)
# ---------------------------------------------------------------------------


def test_single_intercepted_token_would_look_like_replay_but_batch_is_eavesdropping() -> None:
    # Eve guessed right on 1/3 of tokens (F = 1) and wrong on 2/3 (F = 0.5).
    token_fidelities = np.array([1.0] * 1365 + [0.5] * 2731)
    assert classify_state_fidelity(token_fidelities[-1]).verdict is FidelityVerdict.REPLAY_ATTACK
    with pytest.raises(EavesdroppingException) as caught:
        evaluate_batch_fidelity(token_fidelities)
    assert caught.value.state_fidelity == pytest.approx(2 / 3, abs=1e-3)


def test_batch_of_replayed_tokens_is_replay() -> None:
    with pytest.raises(ReplayAttackException):
        evaluate_batch_fidelity(np.full(4096, 0.5))


def test_honest_batch_passes_and_reports_token_count() -> None:
    assessment = evaluate_batch_fidelity(np.full(4096, 0.9706))
    assert assessment.is_secure and assessment.token_count == 4096


def test_non_raising_mode_returns_verdict() -> None:
    assessment = evaluate_batch_fidelity([0.5, 0.5], raise_on_threat=False)
    assert assessment.verdict is FidelityVerdict.REPLAY_ATTACK


def test_mean_is_linear_time_average() -> None:
    assert mean_state_fidelity([1.0, 0.5, 0.5]) == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# Input validation (no silent passes on bad data)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_fidelity_is_rejected(bad_value: float) -> None:
    with pytest.raises(ValueError):
        enforce_fidelity_bounds(bad_value)


def test_empty_batch_is_rejected() -> None:
    with pytest.raises(ValueError):
        evaluate_batch_fidelity([])


def test_float_roundoff_just_above_one_is_clamped() -> None:
    assert enforce_fidelity_bounds(1.0 + 1e-12).state_fidelity == 1.0
