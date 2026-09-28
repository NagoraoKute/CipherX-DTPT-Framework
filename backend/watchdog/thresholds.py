"""
thresholds.py — Statistical Watchdog: Asymmetric dual-threshold forgery detection
(Phase 3, Step 3.2)

Gottesman-Chuang style acceptance levels
----------------------------------------
Bob measures each of the L teleported tokens in its Pauli basis and counts
mismatches X. With m = X / L:

    m <  s_a            AUTHENTICATED  (receiver accepts; the only 200 OK outcome)
    s_a <= m < s_v      VERIFIED_ONLY  (verifier would accept, receiver does not) -> ABORT_FORGERY
    m >= s_v            REJECTED       (fails even the verifier)                  -> ABORT_FORGERY

This matches the agreed rule: any mismatch rate at or above s_a aborts.

Choosing s_a and s_v
--------------------
    e_h  honest mismatch rate of the channel = 1 - F_channel
         (for a pure token |psi>, the chance Bob's projective measurement
          disagrees is exactly 1 - <psi|rho|psi>)
    e_f  forger's per-token mismatch floor. Default 1/6 = 1 - 5/6, because
         the optimal universal 1 -> 2 qubit cloner (Buzek-Hillery) reaches
         fidelity 5/6 at most. A forger with no copy at all sits at 1/2.

The gap (e_h, e_f) is split in thirds (standard GC choice):
    s_a = e_h + (e_f - e_h) / 3,    s_v = e_h + 2 (e_f - e_h) / 3
and 0 <= e_h < s_a < s_v < e_f <= 0.5 is always validated.

Security bounds (two kinds, both exact statements)
--------------------------------------------------
* Hoeffding: rigorous upper bounds valid for any L:
      honest abort      <= exp(-2 L (s_a - e_h)^2)
      forgery accepted  <= exp(-2 L (e_f - s_v)^2)   (conservative: at s_v, not s_a)
      repudiation       <= 2 exp(-L (s_v - s_a)^2 / 2)
  (repudiation = one party sees m < s_a while another sees m >= s_v on copies
   with the same underlying error rate; one of the two must deviate by at
   least (s_v - s_a)/2.)
* Exact binomial tails (scipy.stats.binom) for the i.i.d. per-token model,
  which are much tighter than Hoeffding at hackathon key lengths.

All checks are O(N) or O(1). No AI/ML.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

import numpy as np
from scipy.stats import binom

MAX_MISMATCH_RATE: Final[float] = 0.5
FORGER_MISMATCH_FLOOR_CLONING: Final[float] = 1.0 - 5.0 / 6.0   # 1/6
FORGER_MISMATCH_FLOOR_BLIND: Final[float] = 0.5
_ROUNDING_DIGITS: Final[int] = 9


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ThresholdConfigurationError(ValueError):
    """Raised when thresholds violate 0 <= e_h < s_a < s_v < e_f <= 0.5."""


class ForgeryException(Exception):
    abort_status: str = "ABORT_FORGERY"

    def __init__(self, assessment: "MismatchAssessment") -> None:
        self.assessment = assessment
        super().__init__(
            f"Mismatch rate {assessment.mismatch_rate:.4f} >= s_a = {assessment.s_a:.4f} "
            f"({assessment.verdict.value}): signature rejected as forged."
        )

    def to_payload(self) -> dict[str, object]:
        return {"error": self.abort_status, "detail": str(self), **self.assessment.to_payload()}


# ---------------------------------------------------------------------------
# Threshold model
# ---------------------------------------------------------------------------


def _count_limit(rate: float, key_length: int) -> int:
    """Smallest integer count X with X >= rate * L (round-off safe)."""
    return math.ceil(round(rate * key_length, _ROUNDING_DIGITS))


@dataclass(frozen=True)
class SecurityBounds:
    honest_abort_hoeffding: float
    honest_abort_exact: float
    forgery_acceptance_hoeffding: float
    forgery_acceptance_exact: float
    repudiation_hoeffding: float

    def to_payload(self) -> dict[str, float]:
        return {name: float(value) for name, value in self.__dict__.items()}


@dataclass(frozen=True)
class DualThresholds:
    s_a: float
    s_v: float
    key_length: int
    honest_error_rate: float = 0.0
    forger_mismatch_floor: float = FORGER_MISMATCH_FLOOR_BLIND

    def __post_init__(self) -> None:
        if self.key_length <= 0:
            raise ThresholdConfigurationError("key_length must be positive.")
        values = (self.honest_error_rate, self.s_a, self.s_v, self.forger_mismatch_floor)
        if not all(math.isfinite(v) for v in values):
            raise ThresholdConfigurationError("Threshold values must be finite.")
        if not (0.0 <= self.honest_error_rate < self.s_a < self.s_v < MAX_MISMATCH_RATE):
            raise ThresholdConfigurationError(
                f"Require 0 <= e_h < s_a < s_v < 0.5; got e_h={self.honest_error_rate}, "
                f"s_a={self.s_a}, s_v={self.s_v}."
            )
        if not (self.s_v < self.forger_mismatch_floor <= MAX_MISMATCH_RATE):
            raise ThresholdConfigurationError(
                f"Require s_v < e_f <= 0.5; got s_v={self.s_v}, e_f={self.forger_mismatch_floor}."
            )

    @property
    def authentication_count_limit(self) -> int:
        """Abort when mismatch_count >= this value."""
        return _count_limit(self.s_a, self.key_length)

    @property
    def verification_count_limit(self) -> int:
        return _count_limit(self.s_v, self.key_length)

    def security_bounds(self) -> SecurityBounds:
        L = self.key_length
        e_h, e_f = self.honest_error_rate, self.forger_mismatch_floor
        return SecurityBounds(
            honest_abort_hoeffding=math.exp(-2 * L * (self.s_a - e_h) ** 2),
            honest_abort_exact=float(binom.sf(self.authentication_count_limit - 1, L, e_h)),
            forgery_acceptance_hoeffding=math.exp(-2 * L * (e_f - self.s_v) ** 2),
            forgery_acceptance_exact=float(binom.cdf(self.verification_count_limit - 1, L, e_f)),
            repudiation_hoeffding=min(1.0, 2 * math.exp(-L * (self.s_v - self.s_a) ** 2 / 2)),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "s_a": self.s_a,
            "s_v": self.s_v,
            "key_length": self.key_length,
            "honest_error_rate": self.honest_error_rate,
            "forger_mismatch_floor": self.forger_mismatch_floor,
            "security_bounds": self.security_bounds().to_payload(),
        }


def derive_dual_thresholds(
    key_length: int,
    honest_error_rate: float,
    forger_mismatch_floor: float = FORGER_MISMATCH_FLOOR_CLONING,
) -> DualThresholds:
    """Place s_a and s_v at one-third and two-thirds of the (e_h, e_f) gap."""
    gap = forger_mismatch_floor - honest_error_rate
    if gap <= 0:
        raise ThresholdConfigurationError(
            f"Channel too noisy: honest error {honest_error_rate:.4f} >= forger floor {forger_mismatch_floor:.4f}."
        )
    return DualThresholds(
        s_a=honest_error_rate + gap / 3,
        s_v=honest_error_rate + 2 * gap / 3,
        key_length=key_length,
        honest_error_rate=honest_error_rate,
        forger_mismatch_floor=forger_mismatch_floor,
    )


def honest_error_rate_from_fidelity(channel_fidelity: float) -> float:
    """e_h = 1 - F for projective measurement of a pure token in its own basis."""
    if not 0.0 <= channel_fidelity <= 1.0:
        raise ValueError("channel_fidelity must be in [0, 1].")
    return 1.0 - channel_fidelity


def minimum_key_length(
    honest_error_rate: float,
    security_parameter: float,
    forger_mismatch_floor: float = FORGER_MISMATCH_FLOOR_CLONING,
) -> int:
    """Smallest L for which all three Hoeffding bounds are <= epsilon (thirds split)."""
    if not 0 < security_parameter < 1:
        raise ValueError("security_parameter (epsilon) must be in (0, 1).")
    third = (forger_mismatch_floor - honest_error_rate) / 3
    if third <= 0:
        raise ThresholdConfigurationError("Channel too noisy for any key length.")
    requirement_one_sided = math.log(1 / security_parameter) / (2 * third**2)   # honest abort & forgery
    requirement_repudiation = 2 * math.log(2 / security_parameter) / third**2
    return math.ceil(max(requirement_one_sided, requirement_repudiation))


# ---------------------------------------------------------------------------
# Mismatch evaluation
# ---------------------------------------------------------------------------


class MismatchVerdict(str, Enum):
    AUTHENTICATED = "AUTHENTICATED"
    VERIFIED_ONLY = "VERIFIED_ONLY"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class MismatchAssessment:
    mismatch_count: int
    key_length: int
    s_a: float
    s_v: float
    verdict: MismatchVerdict

    @property
    def mismatch_rate(self) -> float:
        return self.mismatch_count / self.key_length

    @property
    def is_authenticated(self) -> bool:
        return self.verdict is MismatchVerdict.AUTHENTICATED

    def to_payload(self) -> dict[str, object]:
        return {
            "mismatch_count": self.mismatch_count,
            "key_length": self.key_length,
            "mismatch_rate": self.mismatch_rate,
            "s_a": self.s_a,
            "s_v": self.s_v,
            "verdict": self.verdict.value,
        }


def compute_mismatch_count(expected_bits: Sequence[int] | np.ndarray, observed_bits: Sequence[int] | np.ndarray) -> int:
    """O(N) count of positions where Bob's projective outcome differs from Alice's eigenvalue bit."""
    expected = np.asarray(expected_bits)
    observed = np.asarray(observed_bits)
    if expected.shape != observed.shape:
        raise ValueError(f"Shape mismatch: {expected.shape} vs {observed.shape}.")
    return int(np.count_nonzero(expected != observed))


def classify_mismatch(mismatch_count: int, key_length: int, thresholds: DualThresholds) -> MismatchAssessment:
    """Integer comparison against the count limits (no float-equality edge cases)."""
    if key_length != thresholds.key_length:
        raise ThresholdConfigurationError(
            f"Thresholds were derived for L={thresholds.key_length}, but {key_length} tokens were measured."
        )
    if not 0 <= mismatch_count <= key_length:
        raise ValueError("mismatch_count must be in [0, key_length].")

    if mismatch_count < thresholds.authentication_count_limit:
        verdict = MismatchVerdict.AUTHENTICATED
    elif mismatch_count < thresholds.verification_count_limit:
        verdict = MismatchVerdict.VERIFIED_ONLY
    else:
        verdict = MismatchVerdict.REJECTED
    return MismatchAssessment(mismatch_count, key_length, thresholds.s_a, thresholds.s_v, verdict)


def enforce_forgery_bounds(mismatch_count: int, key_length: int, thresholds: DualThresholds) -> MismatchAssessment:
    """Raise ForgeryException unless m < s_a."""
    assessment = classify_mismatch(mismatch_count, key_length, thresholds)
    if not assessment.is_authenticated:
        raise ForgeryException(assessment)
    return assessment


def enforce_forgery_bounds_from_rate(mismatch_rate: float, thresholds: DualThresholds) -> MismatchAssessment:
    """Convenience for callers holding a rate (e.g. unit tests); converts to an integer count."""
    if not 0.0 <= mismatch_rate <= 1.0:
        raise ValueError("mismatch_rate must be in [0, 1].")
    count = round(mismatch_rate * thresholds.key_length)
    return enforce_forgery_bounds(count, thresholds.key_length, thresholds)


# ---------------------------------------------------------------------------
# Visualizer data (Recharts)
# ---------------------------------------------------------------------------


def mismatch_distribution_curve(
    key_length: int, mismatch_probability: float, min_probability: float = 1e-9
) -> list[dict[str, float]]:
    """
    Exact binomial distribution of the observed mismatch rate for a given per-token
    mismatch probability. Plot honest (e_h) vs. attack (e.g. 0.5) curves against
    ReferenceLines at s_a and s_v to show the shift to the right.
    """
    if not 0.0 <= mismatch_probability <= 1.0:
        raise ValueError("mismatch_probability must be in [0, 1].")
    counts = np.arange(key_length + 1)
    pmf = binom.pmf(counts, key_length, mismatch_probability)
    keep = pmf >= min_probability
    return [
        {"mismatch_rate": float(k / key_length), "probability": float(p)}
        for k, p in zip(counts[keep], pmf[keep])
    ]
