"""
attack_simulation_harness.py — Signature sessions, attack injection and the
combined Watchdog evaluation (Phase 3, Step 3.3)

A signature session has two layers, mirroring the GC-style QDS protocol:

  1. Quantum layer: Alice teleports L public-key tokens (Pauli eigenstates chosen
     by the OQRNG) to Bob through Charlie's BSM, over a noisy fiber (qiskit-aer).
     In parallel, a decoy-state pulse train is sent over the same fiber.
  2. Signature claim: the signer reveals the token labels (the private key).
     Bob measures each received token in the claimed basis and counts mismatches.

Honest runs and all four attacks go through the SAME code path; an attack only
changes one physical ingredient:

    INTERCEPT_RESEND  Eve measures each token on the Alice->Charlie fiber in a
                      random Pauli basis and resends (Qiskit measure-and-resend
                      channel = complete dephasing in her basis). Batch F ~ 2/3.
    REPLAY            A recorded BSM broadcast is replayed; Bob corrects a Bell
                      half that was never teleported into -> Bob holds I/2, F = 1/2.
    FORGERY           The quantum channel is untouched, but the forger claims token
                      labels without knowing the private key -> mismatch ~ 1/2.
    PNS               Tokens are untouched; the decoy channel runs with
                      pns_attack=True -> decoy yield collapses, Y1^L <= 0.

Watchdog order (evaluate_signature_session):
    1. Replay        batch fidelity within 0.01 of 0.5          ABORT_REPLAY
    2. Eavesdropping batch fidelity <= 0.6667                   ABORT_EAVESDROP
    3. PNS           decoy rules (watchdog/decoy_stats.py)       ABORT_EAVESDROP (PNS)
    4. Forgery       mismatch count >= s_a * L                   ABORT_FORGERY

Performance: Bob's density matrices depend only on (token, attack branch, noise),
so they are computed once per noise setting with qiskit-aer and cached. Each
session is then O(L) NumPy work plus one decoy-state run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Final

import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import DensityMatrix, state_fidelity
from qiskit_aer import AerSimulator
from qiskit_aer.noise import QuantumError, pauli_error

from quantum_engine.decoy_states import (
    DecoyProtocolConfig,
    DecoyTelemetry,
    FiberChannelConfig,
    run_decoy_protocol,
)
from quantum_engine.oqrng import OpticalQRNG, poisson_histogram
from quantum_engine.teleportation import (
    ALICE_BELL_HALF,
    BOB_BELL_HALF,
    SIGNATURE_QUBIT,
    VALID_BROADCASTS,
    PauliEigenstate,
    apply_fiber_channel,
    bell_state_measurement_gates,
    build_fiber_error,
    create_bell_pair,
    prepare_pauli_eigenstate,
)
from watchdog.decoy_stats import (
    DEFAULT_FALSE_ALARM_PROBABILITY,
    DecoyAssessment,
    PNSAttackException,
    assess_decoy_telemetry,
    enforce_decoy_bounds,
)
from watchdog.fidelity import (
    FidelityThreatException,
    classify_state_fidelity,
    evaluate_batch_fidelity,
)
from watchdog.thresholds import (
    FORGER_MISMATCH_FLOOR_CLONING,
    DualThresholds,
    ForgeryException,
    MismatchAssessment,
    classify_mismatch,
    derive_dual_thresholds,
    enforce_forgery_bounds,
    honest_error_rate_from_fidelity,
    mismatch_distribution_curve,
)

EIGENSTATES: Final[tuple[PauliEigenstate, ...]] = tuple(PauliEigenstate)
EVE_BASES: Final[tuple[str, ...]] = ("Z", "X", "Y")
POISSON_HISTOGRAM_SAMPLES: Final[int] = 5_000

#: Every exception the Watchdog can raise. The API catches exactly this tuple.
WATCHDOG_EXCEPTIONS: Final[tuple[type[Exception], ...]] = (
    FidelityThreatException,
    PNSAttackException,
    ForgeryException,
)


class AttackType(str, Enum):
    NONE = "NONE"
    FORGERY = "FORGERY"
    REPLAY = "REPLAY"
    INTERCEPT_RESEND = "INTERCEPT_RESEND"
    PNS = "PNS"


@dataclass(frozen=True)
class ChannelSettings:
    """Calibrated physical parameters. Changing them recalibrates s_a / s_v (Risk 2)."""

    key_length: int = 4096   # 1024 mislabels ~7.5% of intercept-resend runs as forgery; 4096 -> ~0.25%
    depolarizing_probability: float = 0.02
    amplitude_damping_gamma: float = 0.0
    decoy_pulse_count: int = 1_000_000
    fiber: FiberChannelConfig = field(default_factory=FiberChannelConfig)
    decoy_protocol: DecoyProtocolConfig = field(default_factory=DecoyProtocolConfig)
    forger_mismatch_floor: float = FORGER_MISMATCH_FLOOR_CLONING
    decoy_false_alarm_probability: float = DEFAULT_FALSE_ALARM_PROBABILITY

    def __post_init__(self) -> None:
        if self.key_length <= 0 or self.decoy_pulse_count <= 0:
            raise ValueError("key_length and decoy_pulse_count must be positive.")


# ---------------------------------------------------------------------------
# Qiskit circuits for each branch (deferred-measurement form, exact density matrices)
# ---------------------------------------------------------------------------


def measure_and_resend_channel(eve_basis: str) -> QuantumError:
    """Eve measures in `eve_basis` and resends what she saw == full dephasing in that basis."""
    if eve_basis not in EVE_BASES:
        raise ValueError(f"Unknown basis {eve_basis!r}.")
    return pauli_error([("I", 0.5), (eve_basis, 0.5)])


def build_session_circuit(
    eigenstate: PauliEigenstate,
    fiber_error: QuantumError | None,
    intercept_basis: str | None = None,
) -> QuantumCircuit:
    """Teleportation with optional intercept-resend on the Alice -> Charlie fiber."""
    circuit = QuantumCircuit(3)
    prepare_pauli_eigenstate(circuit, SIGNATURE_QUBIT, eigenstate)
    create_bell_pair(circuit, ALICE_BELL_HALF, BOB_BELL_HALF)
    if intercept_basis is not None:
        circuit.append(measure_and_resend_channel(intercept_basis), [SIGNATURE_QUBIT])
    for qubit in (SIGNATURE_QUBIT, ALICE_BELL_HALF, BOB_BELL_HALF):
        apply_fiber_channel(circuit, qubit, fiber_error)
    bell_state_measurement_gates(circuit)
    circuit.cx(ALICE_BELL_HALF, BOB_BELL_HALF)   # pauli_x_correction
    circuit.cz(SIGNATURE_QUBIT, BOB_BELL_HALF)   # pauli_z_correction
    circuit.save_density_matrix(qubits=[BOB_BELL_HALF], label="bob_rho")
    return circuit


def build_replay_circuit(replayed_broadcast: str, fiber_error: QuantumError | None) -> QuantumCircuit:
    """Bob applies a replayed correction to a Bell half no token was teleported into."""
    if replayed_broadcast not in VALID_BROADCASTS:
        raise ValueError(f"Invalid broadcast {replayed_broadcast!r}.")
    circuit = QuantumCircuit(3)
    create_bell_pair(circuit, ALICE_BELL_HALF, BOB_BELL_HALF)
    apply_fiber_channel(circuit, BOB_BELL_HALF, fiber_error)
    if replayed_broadcast[1] == "1":
        circuit.x(BOB_BELL_HALF)
    if replayed_broadcast[0] == "1":
        circuit.z(BOB_BELL_HALF)
    circuit.save_density_matrix(qubits=[BOB_BELL_HALF], label="bob_rho")
    return circuit


def _simulate_bob_state(circuit: QuantumCircuit) -> DensityMatrix:
    result = AerSimulator(method="density_matrix").run(circuit, shots=1).result()
    return DensityMatrix(result.data(0)["bob_rho"])


def _fidelity_row(bob_state: DensityMatrix) -> np.ndarray:
    """F(bob_state, e) for all six eigenstates e, in PauliEigenstate order."""
    return np.array([state_fidelity(bob_state, e.statevector) for e in EIGENSTATES], dtype=np.float64)


# Cached fidelity tables. Index order: [source ..., target eigenstate].


@lru_cache(maxsize=16)
def honest_fidelity_table(depolarizing_probability: float, amplitude_damping_gamma: float) -> np.ndarray:
    """shape (6, 6): [teleported token, measured-against eigenstate]."""
    fiber_error = build_fiber_error(depolarizing_probability, amplitude_damping_gamma)
    return np.stack([_fidelity_row(_simulate_bob_state(build_session_circuit(e, fiber_error))) for e in EIGENSTATES])


@lru_cache(maxsize=16)
def intercept_fidelity_table(depolarizing_probability: float, amplitude_damping_gamma: float) -> np.ndarray:
    """shape (6, 3, 6): [teleported token, Eve's basis, measured-against eigenstate]."""
    fiber_error = build_fiber_error(depolarizing_probability, amplitude_damping_gamma)
    return np.stack([
        np.stack([_fidelity_row(_simulate_bob_state(build_session_circuit(e, fiber_error, basis))) for basis in EVE_BASES])
        for e in EIGENSTATES
    ])


@lru_cache(maxsize=16)
def replay_fidelity_table(depolarizing_probability: float, amplitude_damping_gamma: float) -> np.ndarray:
    """shape (4, 6): [replayed broadcast, measured-against eigenstate]."""
    fiber_error = build_fiber_error(depolarizing_probability, amplitude_damping_gamma)
    return np.stack([_fidelity_row(_simulate_bob_state(build_replay_circuit(b, fiber_error))) for b in VALID_BROADCASTS])


@lru_cache(maxsize=16)
def calibrate_thresholds(settings: ChannelSettings) -> DualThresholds:
    """s_a / s_v from the worst-case honest token: e_h = 1 - min_e F(e)."""
    table = honest_fidelity_table(settings.depolarizing_probability, settings.amplitude_damping_gamma)
    worst_fidelity = float(np.min(np.diag(table)))
    return derive_dual_thresholds(
        key_length=settings.key_length,
        honest_error_rate=honest_error_rate_from_fidelity(worst_fidelity),
        forger_mismatch_floor=settings.forger_mismatch_floor,
    )


# ---------------------------------------------------------------------------
# Session telemetry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionTelemetry:
    """Raw measurement data of one session. The Watchdog decides purely from this."""

    attack_type: AttackType
    token_indices: np.ndarray            # Alice's true tokens
    claimed_indices: np.ndarray          # labels presented as the signature
    token_fidelities: np.ndarray         # F(Bob's state, true token), per token
    mismatch_probabilities: np.ndarray   # Born-rule P(mismatch) per token
    mismatch_outcomes: np.ndarray        # sampled projective outcomes (bool)
    decoy_telemetry: DecoyTelemetry
    thresholds: DualThresholds
    poisson_samples: np.ndarray
    mean_photon_count: float
    decoy_false_alarm_probability: float = DEFAULT_FALSE_ALARM_PROBABILITY

    @property
    def key_length(self) -> int:
        return int(self.token_indices.size)

    @property
    def mismatch_count(self) -> int:
        return int(np.count_nonzero(self.mismatch_outcomes))

    @property
    def mismatch_rate(self) -> float:
        return self.mismatch_count / self.key_length

    @property
    def batch_state_fidelity(self) -> float:
        return float(np.mean(self.token_fidelities))

    def distribution_payload(self) -> list[dict[str, float]]:
        """Merged Recharts series: honest baseline vs. this session, over mismatch rate."""
        L = self.key_length
        baseline = {p["mismatch_rate"]: p["probability"] for p in mismatch_distribution_curve(L, self.thresholds.honest_error_rate)}
        observed_probability = float(np.mean(self.mismatch_probabilities))
        observed = {p["mismatch_rate"]: p["probability"] for p in mismatch_distribution_curve(L, observed_probability)}
        grid = sorted(set(baseline) | set(observed))
        return [{"mismatch_rate": x, "baseline": baseline.get(x, 0.0), "observed": observed.get(x, 0.0)} for x in grid]

    def to_payload(self, include_distributions: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "attack_type": self.attack_type.value,
            "key_length": self.key_length,
            "state_fidelity": self.batch_state_fidelity,
            "mismatch_count": self.mismatch_count,
            "mismatch_rate": self.mismatch_rate,
            "thresholds": self.thresholds.to_payload(),
            "decoy": self.decoy_telemetry.to_payload(),
        }
        if include_distributions:
            payload["mismatch_distribution"] = self.distribution_payload()
            payload["token_fidelities"] = self.token_fidelities.round(6).tolist()
            payload["poisson_distribution"] = poisson_histogram(self.poisson_samples, self.mean_photon_count)
        return payload


def run_signature_session(
    attack_type: AttackType = AttackType.NONE,
    settings: ChannelSettings | None = None,
    qrng: OpticalQRNG | None = None,
    physics_seed: int | None = None,
) -> SessionTelemetry:
    """Run one session, injecting at most one attack. Never raises on threats."""
    settings = settings or ChannelSettings()
    qrng = qrng or OpticalQRNG()
    physics_rng = np.random.default_rng(physics_seed)
    p, gamma = settings.depolarizing_probability, settings.amplitude_damping_gamma
    L = settings.key_length
    token_indices = qrng.select_signature_tokens(L).token_indices
    claimed_indices = token_indices.copy()

    # Quantum layer: which Bob state does each token end up in?
    if attack_type is AttackType.INTERCEPT_RESEND:
        eve_basis_indices = physics_rng.integers(0, len(EVE_BASES), size=L)
        received_rows = intercept_fidelity_table(p, gamma)[token_indices, eve_basis_indices]
    elif attack_type is AttackType.REPLAY:
        replayed_broadcasts = physics_rng.integers(0, len(VALID_BROADCASTS), size=L)
        received_rows = replay_fidelity_table(p, gamma)[replayed_broadcasts]
    else:
        received_rows = honest_fidelity_table(p, gamma)[token_indices]

    # Signature claim: a forger cannot know the private labels.
    if attack_type is AttackType.FORGERY:
        claimed_indices = physics_rng.integers(0, len(EIGENSTATES), size=L)

    positions = np.arange(L)
    token_fidelities = received_rows[positions, token_indices]
    mismatch_probabilities = np.clip(1.0 - received_rows[positions, claimed_indices], 0.0, 1.0)
    mismatch_outcomes = physics_rng.random(L) < mismatch_probabilities   # Bob's projective measurements

    decoy_telemetry = run_decoy_protocol(
        pulse_count=settings.decoy_pulse_count,
        config=settings.decoy_protocol,
        channel=settings.fiber,
        pns_attack=attack_type is AttackType.PNS,
        qrng=qrng,
        physics_seed=int(physics_rng.integers(0, 2**63 - 1)),
    )

    return SessionTelemetry(
        attack_type=attack_type,
        token_indices=token_indices,
        claimed_indices=claimed_indices,
        token_fidelities=token_fidelities,
        mismatch_probabilities=mismatch_probabilities,
        mismatch_outcomes=mismatch_outcomes,
        decoy_telemetry=decoy_telemetry,
        thresholds=calibrate_thresholds(settings),
        poisson_samples=qrng.photon_counts(POISSON_HISTOGRAM_SAMPLES),
        mean_photon_count=qrng.mean_photon_count,
        decoy_false_alarm_probability=settings.decoy_false_alarm_probability,
    )


# ---------------------------------------------------------------------------
# Watchdog evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WatchdogReport:
    status: str                          # VERIFIED or ABORT_*
    variant: str | None
    fidelity_verdict: str
    decoy_assessment: DecoyAssessment
    mismatch_assessment: MismatchAssessment

    @property
    def is_verified(self) -> bool:
        return self.status == "VERIFIED"

    def to_payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "variant": self.variant,
            "fidelity_verdict": self.fidelity_verdict,
            "decoy": self.decoy_assessment.to_payload(),
            "mismatch": self.mismatch_assessment.to_payload(),
        }


def evaluate_signature_session(telemetry: SessionTelemetry) -> WatchdogReport:
    """Strict, ordered Watchdog. Raises the first matching WATCHDOG_EXCEPTION."""
    fidelity_assessment = evaluate_batch_fidelity(telemetry.token_fidelities, raise_on_threat=True)
    decoy_assessment = enforce_decoy_bounds(telemetry.decoy_telemetry, telemetry.decoy_false_alarm_probability)
    mismatch_assessment = enforce_forgery_bounds(telemetry.mismatch_count, telemetry.key_length, telemetry.thresholds)
    return WatchdogReport(
        status="VERIFIED",
        variant=None,
        fidelity_verdict=fidelity_assessment.verdict.value,
        decoy_assessment=decoy_assessment,
        mismatch_assessment=mismatch_assessment,
    )


def assess_signature_session(telemetry: SessionTelemetry) -> WatchdogReport:
    """Non-raising view of the same ordered rules, for dashboards and logs."""
    fidelity_assessment = classify_state_fidelity(telemetry.batch_state_fidelity, telemetry.key_length)
    decoy_assessment = assess_decoy_telemetry(telemetry.decoy_telemetry, telemetry.decoy_false_alarm_probability)
    mismatch_assessment = classify_mismatch(telemetry.mismatch_count, telemetry.key_length, telemetry.thresholds)

    status, variant = "VERIFIED", None
    if not fidelity_assessment.is_secure:
        status = fidelity_assessment.verdict.value
    elif not decoy_assessment.is_secure:
        status, variant = PNSAttackException.abort_status, PNSAttackException.attack_variant
    elif not mismatch_assessment.is_authenticated:
        status = ForgeryException.abort_status

    return WatchdogReport(
        status=status,
        variant=variant,
        fidelity_verdict=fidelity_assessment.verdict.value,
        decoy_assessment=decoy_assessment,
        mismatch_assessment=mismatch_assessment,
    )


# ---------------------------------------------------------------------------
# Public trigger functions (called by the API)
# ---------------------------------------------------------------------------


def execute_honest_signature(settings: ChannelSettings | None = None, physics_seed: int | None = None) -> SessionTelemetry:
    return run_signature_session(AttackType.NONE, settings, physics_seed=physics_seed)


def execute_forgery_attack(settings: ChannelSettings | None = None, physics_seed: int | None = None) -> SessionTelemetry:
    return run_signature_session(AttackType.FORGERY, settings, physics_seed=physics_seed)


def execute_replay_attack(settings: ChannelSettings | None = None, physics_seed: int | None = None) -> SessionTelemetry:
    return run_signature_session(AttackType.REPLAY, settings, physics_seed=physics_seed)


def execute_intercept_resend_attack(settings: ChannelSettings | None = None, physics_seed: int | None = None) -> SessionTelemetry:
    return run_signature_session(AttackType.INTERCEPT_RESEND, settings, physics_seed=physics_seed)


def execute_pns_attack(settings: ChannelSettings | None = None, physics_seed: int | None = None) -> SessionTelemetry:
    return run_signature_session(AttackType.PNS, settings, physics_seed=physics_seed)


def simulate_attack(attack_type: AttackType | str, settings: ChannelSettings | None = None, physics_seed: int | None = None) -> SessionTelemetry:
    """Single dispatch entry point for the API."""
    return run_signature_session(AttackType(attack_type), settings, physics_seed=physics_seed)
