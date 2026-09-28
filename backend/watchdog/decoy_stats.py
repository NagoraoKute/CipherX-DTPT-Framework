"""
decoy_stats.py — Statistical Watchdog: Photon Number Splitting (PNS) detection
(Phase 3, Step 3.4 — test target: tests/test_decoy_stats.py)

Deterministic rules on the decoy-state telemetry (ABORT_EAVESDROP, PNS variant):

    Rule 1  Single-photon yield collapse
            Y1^L <= 0  ->  abort.
            The Ma-Qi-Zhao-Lo lower bound can only be non-positive when the
            observed gains are inconsistent with ANY physical single-photon
            channel, which is exactly the PNS signature (Eve blocks single
            photons and forwards multi-photon pulses).

    Rule 2  Decoy yield outside its exact acceptance interval
            Under the honest channel, the number of decoy detections is
            Binomial(N_decoy, Q_nu). The acceptance interval [k_lo, k_hi] is
            taken from the exact binomial quantiles so that an honest channel
            falls outside it with probability <= epsilon (default 1e-6).
            A PNS attacker who matches the SIGNAL gain drives the DECOY count
            far below k_lo.

All thresholds are fixed functions of the calibrated channel. No AI/ML.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from scipy.stats import binom

from quantum_engine.decoy_states import DecoyTelemetry, PulseClass

DEFAULT_FALSE_ALARM_PROBABILITY: Final[float] = 1e-6

RULE_Y1_COLLAPSE: Final[str] = "SINGLE_PHOTON_YIELD_COLLAPSE"
RULE_DECOY_YIELD_LOW: Final[str] = "DECOY_YIELD_BELOW_BASELINE"
RULE_DECOY_YIELD_HIGH: Final[str] = "DECOY_YIELD_ABOVE_BASELINE"


@dataclass(frozen=True)
class DecoyAssessment:
    decoy_pulses_sent: int
    decoy_detections: int
    expected_decoy_detections: float
    acceptance_interval: tuple[int, int]
    single_photon_yield_lower_bound: float
    expected_single_photon_yield: float
    false_alarm_probability: float
    violations: tuple[str, ...]

    @property
    def is_secure(self) -> bool:
        return not self.violations

    def to_payload(self) -> dict[str, object]:
        return {
            "decoy_pulses_sent": self.decoy_pulses_sent,
            "decoy_detections": self.decoy_detections,
            "expected_decoy_detections": self.expected_decoy_detections,
            "acceptance_interval": list(self.acceptance_interval),
            "single_photon_yield_lower_bound": self.single_photon_yield_lower_bound,
            "expected_single_photon_yield": self.expected_single_photon_yield,
            "false_alarm_probability": self.false_alarm_probability,
            "violations": list(self.violations),
            "is_secure": self.is_secure,
        }


class PNSAttackException(Exception):
    """PNS variant of the eavesdropping abort. Maps to HTTP 403 ABORT_EAVESDROP."""

    abort_status: str = "ABORT_EAVESDROP"
    attack_variant: str = "PNS"

    def __init__(self, assessment: DecoyAssessment) -> None:
        self.assessment = assessment
        super().__init__(
            "Decoy-state statistics are inconsistent with the calibrated fiber channel "
            f"({', '.join(assessment.violations)}): photon number splitting suspected."
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "error": self.abort_status,
            "variant": self.attack_variant,
            "detail": str(self),
            "decoy_assessment": self.assessment.to_payload(),
        }


def decoy_acceptance_interval(pulses_sent: int, expected_gain: float, false_alarm_probability: float) -> tuple[int, int]:
    """Exact two-sided binomial interval: P(honest count outside) <= false_alarm_probability."""
    if not 0 < false_alarm_probability < 1:
        raise ValueError("false_alarm_probability must be in (0, 1).")
    if pulses_sent <= 0:
        return (0, 0)
    tail = false_alarm_probability / 2
    lower = int(binom.ppf(tail, pulses_sent, expected_gain))
    upper = int(binom.isf(tail, pulses_sent, expected_gain))
    return (lower, upper)


def assess_decoy_telemetry(
    telemetry: DecoyTelemetry,
    false_alarm_probability: float = DEFAULT_FALSE_ALARM_PROBABILITY,
) -> DecoyAssessment:
    """Apply both PNS rules without raising."""
    decoy = telemetry.class_statistics[PulseClass.DECOY]
    lower, upper = decoy_acceptance_interval(decoy.pulses_sent, decoy.expected_gain, false_alarm_probability)

    violations: list[str] = []
    if telemetry.single_photon_yield_lower_bound <= 0:
        violations.append(RULE_Y1_COLLAPSE)
    if decoy.detections < lower:
        violations.append(RULE_DECOY_YIELD_LOW)
    elif decoy.detections > upper:
        violations.append(RULE_DECOY_YIELD_HIGH)

    return DecoyAssessment(
        decoy_pulses_sent=decoy.pulses_sent,
        decoy_detections=decoy.detections,
        expected_decoy_detections=decoy.pulses_sent * decoy.expected_gain,
        acceptance_interval=(lower, upper),
        single_photon_yield_lower_bound=telemetry.single_photon_yield_lower_bound,
        expected_single_photon_yield=telemetry.expected_single_photon_yield,
        false_alarm_probability=false_alarm_probability,
        violations=tuple(violations),
    )


def enforce_decoy_bounds(
    telemetry: DecoyTelemetry,
    false_alarm_probability: float = DEFAULT_FALSE_ALARM_PROBABILITY,
) -> DecoyAssessment:
    """Raise PNSAttackException if either PNS rule fires."""
    assessment = assess_decoy_telemetry(telemetry, false_alarm_probability)
    if not assessment.is_secure:
        raise PNSAttackException(assessment)
    return assessment
