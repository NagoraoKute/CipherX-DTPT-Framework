"""
fidelity.py — Statistical Watchdog: Replay & Eavesdropping detection (Phase 3, Step 3.1)

Deterministic rules (evaluated IN THIS ORDER):
    1. Replay attack     if isclose(F, 0.5, atol=0.01)  -> ABORT_REPLAY
       A replayed BSM broadcast applied to an unentangled (maximally mixed)
       qubit leaves Bob with I/2, whose fidelity with ANY pure signature
       state is exactly 1/2. This must be checked first, because 0.5 also
       satisfies the eavesdropping rule below.
    2. Intercept-resend  if F <= 0.6667                  -> ABORT_EAVESDROP
       2/3 is the best average fidelity achievable by any measure-and-prepare
       (classical) strategy for an unknown qubit.
    3. Otherwise                                          -> SECURE

Per-token vs. batch fidelity
----------------------------
The 2/3 limit is an AVERAGE over signature tokens. A single intercepted
token can land on F = 1 (Eve guessed the basis) or F = 0.5 (wrong basis),
and a lone 0.5 would be misread as a replay. `evaluate_batch_fidelity`
averages over the whole signature first (O(N)) and is the entry point the
API should use; `enforce_fidelity_bounds` on a single value is for unit
tests and single-token diagnostics.

No AI/ML, no heuristics: every decision is a fixed comparison.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

import numpy as np
from qiskit.quantum_info import DensityMatrix, Statevector, state_fidelity

REPLAY_FIDELITY: Final[float] = 0.5
REPLAY_FIDELITY_TOLERANCE: Final[float] = 0.01
CLASSICAL_TELEPORTATION_LIMIT: Final[float] = 0.6667   # 2/3, rounded up (conservative)
_NUMERICAL_SLACK: Final[float] = 1e-9                  # float round-off on [0, 1]


# ---------------------------------------------------------------------------
# Exceptions (status strings match DATA_MODEL.md SignatureLogs.status)
# ---------------------------------------------------------------------------


class FidelityThreatException(Exception):
    """Base class for fidelity-based aborts. The API maps these to HTTP 403."""

    abort_status: str = "ABORT_UNKNOWN"

    def __init__(self, state_fidelity: float, message: str) -> None:
        super().__init__(message)
        self.state_fidelity = state_fidelity

    def to_payload(self) -> dict[str, object]:
        return {"error": self.abort_status, "state_fidelity": self.state_fidelity, "detail": str(self)}


class ReplayAttackException(FidelityThreatException):
    abort_status = "ABORT_REPLAY"


class EavesdroppingException(FidelityThreatException):
    abort_status = "ABORT_EAVESDROP"


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


class FidelityVerdict(str, Enum):
    SECURE = "SECURE"
    REPLAY_ATTACK = "ABORT_REPLAY"
    EAVESDROPPING = "ABORT_EAVESDROP"


@dataclass(frozen=True)
class FidelityAssessment:
    state_fidelity: float
    verdict: FidelityVerdict
    token_count: int = 1

    @property
    def is_secure(self) -> bool:
        return self.verdict is FidelityVerdict.SECURE

    @property
    def margin_above_classical_limit(self) -> float:
        """Positive = secure headroom; negative = below the 2/3 limit."""
        return self.state_fidelity - CLASSICAL_TELEPORTATION_LIMIT

    def to_payload(self) -> dict[str, object]:
        return {
            "state_fidelity": self.state_fidelity,
            "verdict": self.verdict.value,
            "token_count": self.token_count,
            "classical_limit": CLASSICAL_TELEPORTATION_LIMIT,
            "replay_band": [REPLAY_FIDELITY - REPLAY_FIDELITY_TOLERANCE, REPLAY_FIDELITY + REPLAY_FIDELITY_TOLERANCE],
            "margin_above_classical_limit": self.margin_above_classical_limit,
        }


# ---------------------------------------------------------------------------
# Fidelity computation
# ---------------------------------------------------------------------------


def validate_fidelity(value: float) -> float:
    """Reject NaN/inf/out-of-range values; clamp harmless float round-off."""
    fidelity = float(value)
    if not math.isfinite(fidelity):
        raise ValueError(f"State fidelity must be finite, got {value!r}.")
    if fidelity < -_NUMERICAL_SLACK or fidelity > 1.0 + _NUMERICAL_SLACK:
        raise ValueError(f"State fidelity must lie in [0, 1], got {fidelity}.")
    return min(1.0, max(0.0, fidelity))


def compute_state_fidelity(
    received_state: DensityMatrix | Statevector | np.ndarray,
    expected_state: Statevector | np.ndarray,
) -> float:
    """F = <psi| rho |psi> for Bob's received state rho and Alice's pure token |psi>."""
    rho = received_state if isinstance(received_state, (DensityMatrix, Statevector)) else DensityMatrix(received_state)
    psi = expected_state if isinstance(expected_state, Statevector) else Statevector(expected_state)
    return validate_fidelity(state_fidelity(rho, psi))


# ---------------------------------------------------------------------------
# Deterministic decision rules
# ---------------------------------------------------------------------------


def classify_state_fidelity(value: float, token_count: int = 1) -> FidelityAssessment:
    """Apply the agreed rules without raising. Replay is checked BEFORE eavesdropping."""
    fidelity = validate_fidelity(value)
    # Inclusive band 0.5 +/- 0.01. np.isclose alone rejects 0.51 (0.51 - 0.5 = 0.0100000000000000089).
    if abs(fidelity - REPLAY_FIDELITY) <= REPLAY_FIDELITY_TOLERANCE + _NUMERICAL_SLACK:
        verdict = FidelityVerdict.REPLAY_ATTACK
    elif fidelity <= CLASSICAL_TELEPORTATION_LIMIT:
        verdict = FidelityVerdict.EAVESDROPPING
    else:
        verdict = FidelityVerdict.SECURE
    return FidelityAssessment(state_fidelity=fidelity, verdict=verdict, token_count=token_count)


def raise_for_verdict(assessment: FidelityAssessment) -> FidelityAssessment:
    """Raise the matching exception for a non-secure assessment; pass SECURE through."""
    if assessment.verdict is FidelityVerdict.REPLAY_ATTACK:
        raise ReplayAttackException(
            assessment.state_fidelity,
            f"F = {assessment.state_fidelity:.4f} is within {REPLAY_FIDELITY_TOLERANCE} of 0.5: "
            "Pauli corrections were applied to an unentangled state (replayed BSM broadcast).",
        )
    if assessment.verdict is FidelityVerdict.EAVESDROPPING:
        raise EavesdroppingException(
            assessment.state_fidelity,
            f"F = {assessment.state_fidelity:.4f} <= {CLASSICAL_TELEPORTATION_LIMIT}: "
            "fidelity is at or below the classical measure-and-prepare limit (intercept-resend).",
        )
    return assessment


def enforce_fidelity_bounds(value: float) -> FidelityAssessment:
    """Single-value check; raises ReplayAttackException or EavesdroppingException."""
    return raise_for_verdict(classify_state_fidelity(value))


def mean_state_fidelity(token_fidelities: Sequence[float] | np.ndarray) -> float:
    """O(N) average fidelity over all signature tokens."""
    values = np.asarray(token_fidelities, dtype=np.float64)
    if values.size == 0:
        raise ValueError("At least one token fidelity is required.")
    for value in (values.min(), values.max()):
        validate_fidelity(value)
    return validate_fidelity(float(values.mean()))


def evaluate_batch_fidelity(token_fidelities: Sequence[float] | np.ndarray, raise_on_threat: bool = True) -> FidelityAssessment:
    """Primary Watchdog entry point: average over the signature, then apply the rules."""
    values = np.asarray(token_fidelities, dtype=np.float64)
    assessment = classify_state_fidelity(mean_state_fidelity(values), token_count=int(values.size))
    return raise_for_verdict(assessment) if raise_on_threat else assessment
