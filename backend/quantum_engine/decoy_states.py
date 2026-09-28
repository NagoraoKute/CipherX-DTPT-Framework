"""
decoy_states.py — Decoy-State intensity modulation and channel telemetry
(Phase 2, Step 2.1 — feeds PNS detection in the Watchdog)

Model (vacuum + weak decoy method; Ma, Qi, Zhao & Lo, PRA 72, 012326, 2005)
---------------------------------------------------------------------------
* Alice chooses each pulse's class with an OQRNG-seeded generator: SIGNAL (mu), weak DECOY
  (nu) or VACUUM (0). Phase-randomised coherent pulses carry a Poisson
  number of photons with mean equal to the class intensity.
* The fiber has transmittance eta = 10^(-alpha * L / 10) * eta_detector.
  Each photon survives independently, so detections are binomial.
* A click with at least one signal photon is wrong with probability e_d
  (misalignment). A click from a dark count alone is wrong with probability 1/2.

Exact expected values for this model (used as the honest baseline):
    Q(x) = 1 - (1 - Y0) * exp(-eta * x)                     (gain / yield rate)
    E(x) * Q(x) = e_d * (1 - exp(-eta * x)) + 0.5 * Y0 * exp(-eta * x)

Discrete-variable caveat (Decision Log, Risk 1): Qiskit simulates qubits,
not multi-photon pulses. This module models the optical layer with exact
photon-number statistics in NumPy; the teleported signature token itself
is still the single qubit in teleportation.py.

PNS attack (for the Attack Simulation Harness)
----------------------------------------------
Eve measures photon number non-destructively, blocks every single-photon
pulse, keeps one photon from each multi-photon pulse and forwards the rest
over a lossless line. She forwards just enough multi-photon pulses to make
the SIGNAL gain match the honest baseline. Because weak decoys contain far
fewer multi-photon pulses, the DECOY gain collapses, and the single-photon
yield bound Y1^L drops, which is what the Watchdog flags.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Final

import numpy as np
from scipy.stats import poisson

from quantum_engine.oqrng import OpticalQRNG

DARK_COUNT_ERROR_PROBABILITY: Final[float] = 0.5
_PHOTON_NUMBER_CUTOFF: Final[int] = 80   # Poisson tail beyond this is < 1e-60 for mu <= 1


class PulseClass(IntEnum):
    SIGNAL = 0
    DECOY = 1
    VACUUM = 2


@dataclass(frozen=True)
class DecoyProtocolConfig:
    """Alice's intensity settings and class probabilities."""

    signal_intensity: float = 0.5
    decoy_intensity: float = 0.1
    signal_probability: float = 0.7
    decoy_probability: float = 0.2
    vacuum_probability: float = 0.1

    def __post_init__(self) -> None:
        if not 0.0 < self.decoy_intensity < self.signal_intensity <= 1.0:
            raise ValueError("Require 0 < decoy_intensity < signal_intensity <= 1.")
        probabilities = (self.signal_probability, self.decoy_probability, self.vacuum_probability)
        if any(p <= 0 for p in probabilities):
            raise ValueError("Each pulse class needs a positive probability.")
        if not math.isclose(sum(probabilities), 1.0, abs_tol=1e-9):
            raise ValueError("Class probabilities must sum to 1.")

    def intensity_of(self, pulse_class: PulseClass) -> float:
        return {
            PulseClass.SIGNAL: self.signal_intensity,
            PulseClass.DECOY: self.decoy_intensity,
            PulseClass.VACUUM: 0.0,
        }[pulse_class]


@dataclass(frozen=True)
class FiberChannelConfig:
    """Telecom C-band fiber + detector parameters (TRD Section 2)."""

    distance_km: float = 100.0
    attenuation_db_per_km: float = 0.2      # standard SMF-28 at 1550 nm
    detector_efficiency: float = 0.8        # superconducting nanowire detector
    dark_count_probability: float = 1e-6    # Y0, per pulse window
    misalignment_error: float = 0.015       # e_d

    def __post_init__(self) -> None:
        if self.distance_km < 0 or self.attenuation_db_per_km < 0:
            raise ValueError("Distance and attenuation must be non-negative.")
        if not 0 < self.detector_efficiency <= 1:
            raise ValueError("detector_efficiency must be in (0, 1].")
        if not 0 <= self.dark_count_probability < 1:
            raise ValueError("dark_count_probability must be in [0, 1).")
        if not 0 <= self.misalignment_error < 0.5:
            raise ValueError("misalignment_error must be in [0, 0.5).")

    @property
    def fiber_transmittance(self) -> float:
        return 10 ** (-self.attenuation_db_per_km * self.distance_km / 10)

    @property
    def transmittance(self) -> float:
        """Overall eta: fiber loss times detector efficiency."""
        return self.fiber_transmittance * self.detector_efficiency


@dataclass(frozen=True)
class PulseTrain:
    """Alice's modulated pulse sequence."""

    pulse_classes: np.ndarray   # int8, values from PulseClass
    intensities: np.ndarray     # float64 mean photon number per pulse
    config: DecoyProtocolConfig

    def __len__(self) -> int:
        return int(self.pulse_classes.size)

    def class_mask(self, pulse_class: PulseClass) -> np.ndarray:
        return self.pulse_classes == int(pulse_class)


@dataclass(frozen=True)
class DetectionRecord:
    """Bob's per-pulse detection outcomes."""

    detected: np.ndarray     # bool
    bit_error: np.ndarray    # bool (only meaningful where detected)


@dataclass(frozen=True)
class IntensityClassStatistics:
    pulse_class: PulseClass
    intensity: float
    pulses_sent: int
    detections: int
    errors: int
    expected_gain: float
    expected_qber: float

    @property
    def gain(self) -> float:
        """Observed yield rate: fraction of pulses in this class that clicked."""
        return self.detections / self.pulses_sent if self.pulses_sent else 0.0

    @property
    def qber(self) -> float:
        """Observed bit error rate among detections of this class."""
        return self.errors / self.detections if self.detections else 0.0


@dataclass(frozen=True)
class DecoyTelemetry:
    """Everything the Watchdog needs for PNS detection. Maps to the DecoyTelemetry table."""

    class_statistics: dict[PulseClass, IntensityClassStatistics]
    single_photon_yield_lower_bound: float
    expected_single_photon_yield: float
    single_photon_error_upper_bound: float | None
    channel: FiberChannelConfig = field(repr=False)

    @property
    def yield_rate(self) -> float:
        return self.class_statistics[PulseClass.DECOY].gain

    @property
    def ber_decoy(self) -> float:
        return self.class_statistics[PulseClass.DECOY].qber

    def to_record(self) -> dict[str, float]:
        """Row for the DecoyTelemetry table (transaction_id is added by the API layer)."""
        return {"yield_rate": self.yield_rate, "ber_decoy": self.ber_decoy}

    def to_payload(self) -> dict[str, object]:
        """JSON-ready summary for the dashboard."""
        return {
            "classes": {
                stats.pulse_class.name: {
                    "intensity": stats.intensity,
                    "pulses_sent": stats.pulses_sent,
                    "detections": stats.detections,
                    "gain": stats.gain,
                    "expected_gain": stats.expected_gain,
                    "qber": stats.qber,
                    "expected_qber": stats.expected_qber,
                }
                for stats in self.class_statistics.values()
            },
            "single_photon_yield_lower_bound": self.single_photon_yield_lower_bound,
            "expected_single_photon_yield": self.expected_single_photon_yield,
            "single_photon_error_upper_bound": self.single_photon_error_upper_bound,
            **self.to_record(),
        }


# ---------------------------------------------------------------------------
# Alice: intensity modulation
# ---------------------------------------------------------------------------


def assign_pulse_intensities(
    pulse_count: int,
    config: DecoyProtocolConfig | None = None,
    qrng: OpticalQRNG | None = None,
) -> PulseTrain:
    """Randomly assign SIGNAL / DECOY / VACUUM to each pulse (OQRNG-seeded generator)."""
    if pulse_count <= 0:
        raise ValueError("pulse_count must be positive.")
    config = config or DecoyProtocolConfig()
    modulation_rng = (qrng or OpticalQRNG()).seeded_generator()

    pulse_classes = modulation_rng.choice(
        np.array([PulseClass.SIGNAL, PulseClass.DECOY, PulseClass.VACUUM], dtype=np.int8),
        size=pulse_count,
        p=[config.signal_probability, config.decoy_probability, config.vacuum_probability],
    )
    intensities = np.zeros(pulse_count, dtype=np.float64)
    intensities[pulse_classes == PulseClass.SIGNAL] = config.signal_intensity
    intensities[pulse_classes == PulseClass.DECOY] = config.decoy_intensity
    return PulseTrain(pulse_classes=pulse_classes, intensities=intensities, config=config)


# ---------------------------------------------------------------------------
# Exact honest-channel baseline
# ---------------------------------------------------------------------------


def expected_gain(intensity: float, channel: FiberChannelConfig) -> float:
    return 1.0 - (1.0 - channel.dark_count_probability) * math.exp(-channel.transmittance * intensity)


def expected_qber(intensity: float, channel: FiberChannelConfig) -> float:
    no_photon = math.exp(-channel.transmittance * intensity)
    error_gain = (
        channel.misalignment_error * (1.0 - no_photon)
        + DARK_COUNT_ERROR_PROBABILITY * channel.dark_count_probability * no_photon
    )
    return error_gain / expected_gain(intensity, channel)


def pns_forward_fraction(signal_intensity: float, channel: FiberChannelConfig) -> float:
    """
    Fraction of multi-photon pulses Eve must forward so the SIGNAL gain matches
    the honest baseline (she keeps one photon, forwards n-1 losslessly).
    """
    photon_numbers = np.arange(2, _PHOTON_NUMBER_CUTOFF)
    forwarded_click_probability = 1.0 - (1.0 - channel.detector_efficiency) ** (photon_numbers - 1)
    eve_photon_gain = float(np.sum(poisson.pmf(photon_numbers, signal_intensity) * forwarded_click_probability))
    honest_photon_gain = 1.0 - math.exp(-channel.transmittance * signal_intensity)
    return min(1.0, honest_photon_gain / eve_photon_gain) if eve_photon_gain > 0 else 0.0


# ---------------------------------------------------------------------------
# Channel simulation
# ---------------------------------------------------------------------------


def simulate_transmission(
    pulse_train: PulseTrain,
    channel: FiberChannelConfig | None = None,
    pns_attack: bool = False,
    seed: int | None = None,
) -> DetectionRecord:
    """Vectorised O(N) photon-level simulation of the fiber and Bob's detector."""
    channel = channel or FiberChannelConfig()
    physics_rng = np.random.default_rng(seed)
    pulse_count = len(pulse_train)

    photon_numbers = physics_rng.poisson(pulse_train.intensities)

    if pns_attack:
        forward_fraction = pns_forward_fraction(pulse_train.config.signal_intensity, channel)
        forwarded = (photon_numbers >= 2) & (physics_rng.random(pulse_count) < forward_fraction)
        remaining_photons = np.where(forwarded, photon_numbers - 1, 0)
        arriving_photons = physics_rng.binomial(remaining_photons, channel.detector_efficiency)
    else:
        arriving_photons = physics_rng.binomial(photon_numbers, channel.transmittance)

    photon_click = arriving_photons > 0
    dark_click = physics_rng.random(pulse_count) < channel.dark_count_probability
    detected = photon_click | dark_click

    error_probability = np.where(photon_click, channel.misalignment_error, DARK_COUNT_ERROR_PROBABILITY)
    bit_error = detected & (physics_rng.random(pulse_count) < error_probability)
    return DetectionRecord(detected=detected, bit_error=bit_error)


# ---------------------------------------------------------------------------
# Bob: isolate decoys and compute telemetry
# ---------------------------------------------------------------------------


def single_photon_yield_lower_bound(
    signal_gain: float, decoy_gain: float, vacuum_yield: float, mu: float, nu: float
) -> float:
    """Ma-Qi-Zhao-Lo vacuum + weak decoy lower bound on Y1."""
    return (mu / (mu * nu - nu**2)) * (
        decoy_gain * math.exp(nu)
        - signal_gain * math.exp(mu) * nu**2 / mu**2
        - (mu**2 - nu**2) / mu**2 * vacuum_yield
    )


def single_photon_error_upper_bound(
    decoy_gain: float, decoy_qber: float, vacuum_yield: float, nu: float, y1_lower: float
) -> float | None:
    """Upper bound on e1; None when Y1^L <= 0 (no single-photon security left)."""
    if y1_lower <= 0:
        return None
    return (decoy_qber * decoy_gain * math.exp(nu) - DARK_COUNT_ERROR_PROBABILITY * vacuum_yield) / (y1_lower * nu)


def compute_decoy_telemetry(
    pulse_train: PulseTrain,
    detection_record: DetectionRecord,
    channel: FiberChannelConfig | None = None,
) -> DecoyTelemetry:
    """Per-class gain and QBER, honest baseline, and single-photon bounds. O(N)."""
    channel = channel or FiberChannelConfig()
    config = pulse_train.config

    class_statistics: dict[PulseClass, IntensityClassStatistics] = {}
    for pulse_class in PulseClass:
        mask = pulse_train.class_mask(pulse_class)
        intensity = config.intensity_of(pulse_class)
        class_statistics[pulse_class] = IntensityClassStatistics(
            pulse_class=pulse_class,
            intensity=intensity,
            pulses_sent=int(np.count_nonzero(mask)),
            detections=int(np.count_nonzero(detection_record.detected[mask])),
            errors=int(np.count_nonzero(detection_record.bit_error[mask])),
            expected_gain=expected_gain(intensity, channel),
            expected_qber=expected_qber(intensity, channel),
        )

    signal = class_statistics[PulseClass.SIGNAL]
    decoy = class_statistics[PulseClass.DECOY]
    vacuum = class_statistics[PulseClass.VACUUM]

    y1_lower = single_photon_yield_lower_bound(
        signal.gain, decoy.gain, vacuum.gain, config.signal_intensity, config.decoy_intensity
    )
    return DecoyTelemetry(
        class_statistics=class_statistics,
        single_photon_yield_lower_bound=y1_lower,
        expected_single_photon_yield=channel.dark_count_probability + channel.transmittance,
        single_photon_error_upper_bound=single_photon_error_upper_bound(
            decoy.gain, decoy.qber, vacuum.gain, config.decoy_intensity, y1_lower
        ),
        channel=channel,
    )


def run_decoy_protocol(
    pulse_count: int = 1_000_000,
    config: DecoyProtocolConfig | None = None,
    channel: FiberChannelConfig | None = None,
    pns_attack: bool = False,
    qrng: OpticalQRNG | None = None,
    physics_seed: int | None = None,
) -> DecoyTelemetry:
    """End-to-end: modulate -> transmit -> isolate decoys -> telemetry."""
    channel = channel or FiberChannelConfig()
    pulse_train = assign_pulse_intensities(pulse_count, config, qrng)
    detection_record = simulate_transmission(pulse_train, channel, pns_attack=pns_attack, seed=physics_seed)
    return compute_decoy_telemetry(pulse_train, detection_record, channel)
