"""
teleportation.py — DTPT Quantum Engine (Phase 2, Step 2.2 / 2.3)

Three-node Measurement-Device-Independent (MDI) teleportation for the
Dual-Threshold Projective Teleportation (DTPT) Framework.

Qubit layout (one signature token per circuit):
    q0  signature_qubit   Alice's Pauli-eigenstate signature token
    q1  alice_bell_half   Alice's half of the |Phi+> pair (routed to Charlie)
    q2  bob_bell_half     Bob's half of the |Phi+> pair

Roles:
    Alice   prepares the signature token in one of the six Pauli eigenstates.
    Charlie (untrusted) performs the Bell-State Measurement (CNOT + H + measure)
            on q0 and q1 and broadcasts two classical bits.
    Bob     applies the deterministic Pauli correction selected by the broadcast
            and performs a projective measurement in the token's basis.

Classical broadcast convention (string "zx", matches testing.md Test 2.3):
    "00" -> I      "01" -> sigma_x      "10" -> sigma_z      "11" -> sigma_z sigma_x
    z_bit = Charlie's measurement of q0 (after H)  -> controls sigma_z
    x_bit = Charlie's measurement of q1            -> controls sigma_x

Determinism: no AI/ML, no heuristics. Every result here is either an exact
linear-algebra evolution (qiskit.quantum_info) or an exact density-matrix
simulation (qiskit-aer, method="density_matrix", no sampling). The only
sampled path is `run_projective_verification`, whose shot counts feed the
Chernoff-Hoeffding thresholds in watchdog/thresholds.py.

Requires: qiskit >= 1.0 (tested on 2.x), qiskit-aer >= 0.14, numpy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Final

import numpy as np
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.quantum_info import DensityMatrix, Operator, Statevector, partial_trace, state_fidelity
from qiskit_aer import AerSimulator
from qiskit_aer.noise import QuantumError, amplitude_damping_error, depolarizing_error

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SIGNATURE_QUBIT: Final[int] = 0
ALICE_BELL_HALF: Final[int] = 1
BOB_BELL_HALF: Final[int] = 2

_SQRT_HALF: Final[float] = 1.0 / np.sqrt(2.0)

PAULI_I: Final[np.ndarray] = np.array([[1, 0], [0, 1]], dtype=complex)
PAULI_X: Final[np.ndarray] = np.array([[0, 1], [1, 0]], dtype=complex)
PAULI_Z: Final[np.ndarray] = np.array([[1, 0], [0, -1]], dtype=complex)

#: Deterministic correction lookup: broadcast "zx" -> Bob's Pauli operator.
PAULI_CORRECTION_TABLE: Final[dict[str, np.ndarray]] = {
    "00": PAULI_I,
    "01": PAULI_X,
    "10": PAULI_Z,
    "11": PAULI_Z @ PAULI_X,
}

VALID_BROADCASTS: Final[tuple[str, ...]] = tuple(PAULI_CORRECTION_TABLE.keys())


# ---------------------------------------------------------------------------
# Pauli eigenstates (GC-style signature alphabet)
# ---------------------------------------------------------------------------


class PauliEigenstate(str, Enum):
    """The six single-qubit Pauli eigenstates used as signature tokens."""

    Z_PLUS = "|0>"
    Z_MINUS = "|1>"
    X_PLUS = "|+>"
    X_MINUS = "|->"
    Y_PLUS = "|+i>"
    Y_MINUS = "|-i>"

    @property
    def basis(self) -> str:
        """Pauli basis of the eigenstate: 'Z', 'X' or 'Y'."""
        return self.name[0]

    @property
    def eigenvalue_bit(self) -> int:
        """0 for the +1 eigenvalue, 1 for the -1 eigenvalue."""
        return 0 if self.name.endswith("PLUS") else 1

    @property
    def statevector(self) -> Statevector:
        vectors: dict[PauliEigenstate, list[complex]] = {
            PauliEigenstate.Z_PLUS: [1, 0],
            PauliEigenstate.Z_MINUS: [0, 1],
            PauliEigenstate.X_PLUS: [_SQRT_HALF, _SQRT_HALF],
            PauliEigenstate.X_MINUS: [_SQRT_HALF, -_SQRT_HALF],
            PauliEigenstate.Y_PLUS: [_SQRT_HALF, 1j * _SQRT_HALF],
            PauliEigenstate.Y_MINUS: [_SQRT_HALF, -1j * _SQRT_HALF],
        }
        return Statevector(np.array(vectors[self], dtype=complex))

    @classmethod
    def from_index(cls, index: int) -> "PauliEigenstate":
        """Map an integer (e.g. an OQRNG Poisson sample) onto the alphabet, mod 6."""
        members = list(cls)
        return members[int(index) % len(members)]


def prepare_pauli_eigenstate(circuit: QuantumCircuit, qubit: int, eigenstate: PauliEigenstate) -> None:
    """Rotate |0> on `qubit` into the requested Pauli eigenstate."""
    if eigenstate.eigenvalue_bit == 1:
        circuit.x(qubit)                  # |0> -> |1>
    if eigenstate.basis == "X":
        circuit.h(qubit)                  # |0>,|1> -> |+>,|->
    elif eigenstate.basis == "Y":
        circuit.h(qubit)
        circuit.s(qubit)                  # |+>,|-> -> |+i>,|-i>


def rotate_to_computational_basis(circuit: QuantumCircuit, qubit: int, basis: str) -> None:
    """Inverse basis rotation so a Z measurement acts as a projective measurement in `basis`."""
    if basis == "X":
        circuit.h(qubit)
    elif basis == "Y":
        circuit.sdg(qubit)
        circuit.h(qubit)
    elif basis != "Z":
        raise ValueError(f"Unknown Pauli basis: {basis!r}")


# ---------------------------------------------------------------------------
# Circuit building blocks
# ---------------------------------------------------------------------------


def create_bell_pair(circuit: QuantumCircuit, qubit_a: int, qubit_b: int) -> None:
    """Prepare |Phi+> = (|00> + |11>)/sqrt(2) between qubit_a and qubit_b."""
    circuit.h(qubit_a)
    circuit.cx(qubit_a, qubit_b)


def apply_fiber_channel(circuit: QuantumCircuit, qubit: int, fiber_error: QuantumError | None) -> None:
    """Insert the fiber-optic noise channel (depolarizing + amplitude damping) on `qubit`."""
    if fiber_error is not None:
        circuit.append(fiber_error, [qubit])


def bell_state_measurement_gates(circuit: QuantumCircuit) -> None:
    """Charlie's BSM rotation: CNOT(signature -> alice_half) then H(signature)."""
    circuit.cx(SIGNATURE_QUBIT, ALICE_BELL_HALF)
    circuit.h(SIGNATURE_QUBIT)


def build_fiber_error(depolarizing_probability: float, amplitude_damping_gamma: float) -> QuantumError | None:
    """
    Single-qubit fiber channel for qiskit-aer.

    depolarizing_probability: depolarizing parameter p in [0, 4/3] (Aer convention).
    amplitude_damping_gamma:  photon-loss style damping gamma in [0, 1].
    Returns None for a perfect (noiseless) fiber.
    """
    if depolarizing_probability < 0 or amplitude_damping_gamma < 0:
        raise ValueError("Noise parameters must be non-negative.")
    if depolarizing_probability == 0 and amplitude_damping_gamma == 0:
        return None
    return depolarizing_error(depolarizing_probability, 1).compose(
        amplitude_damping_error(amplitude_damping_gamma)
    )


# ---------------------------------------------------------------------------
# Circuit constructors
# ---------------------------------------------------------------------------


def build_teleportation_circuit(
    eigenstate: PauliEigenstate,
    fiber_error: QuantumError | None = None,
    measure_bob: bool = True,
) -> QuantumCircuit:
    """
    Full MDI teleportation with mid-circuit BSM and classically-conditioned
    Pauli corrections (Qiskit dynamic circuits, `if_test`).

    Classical registers:
        charlie_z  (1 bit)  BSM outcome of q0 -> drives Bob's sigma_z
        charlie_x  (1 bit)  BSM outcome of q1 -> drives Bob's sigma_x
        bob_result (1 bit)  Bob's projective measurement in the token basis
                            (0 = matches Alice's eigenvalue, 1 = mismatch)
    """
    qreg = QuantumRegister(3, "q")
    charlie_z = ClassicalRegister(1, "charlie_z")
    charlie_x = ClassicalRegister(1, "charlie_x")
    registers: list[QuantumRegister | ClassicalRegister] = [qreg, charlie_z, charlie_x]
    bob_result: ClassicalRegister | None = None
    if measure_bob:
        bob_result = ClassicalRegister(1, "bob_result")
        registers.append(bob_result)

    circuit = QuantumCircuit(*registers, name=f"dtpt_teleport_{eigenstate.name}")

    # Alice: signature token
    prepare_pauli_eigenstate(circuit, SIGNATURE_QUBIT, eigenstate)
    # Entanglement source: |Phi+> shared by Alice and Bob
    create_bell_pair(circuit, ALICE_BELL_HALF, BOB_BELL_HALF)
    circuit.barrier(label="entangled")

    # Fiber transit to Charlie (both of Alice's photons) and to Bob
    apply_fiber_channel(circuit, SIGNATURE_QUBIT, fiber_error)
    apply_fiber_channel(circuit, ALICE_BELL_HALF, fiber_error)
    apply_fiber_channel(circuit, BOB_BELL_HALF, fiber_error)
    circuit.barrier(label="fiber")

    # Charlie: Bell-State Measurement
    bell_state_measurement_gates(circuit)
    circuit.measure(SIGNATURE_QUBIT, charlie_z[0])
    circuit.measure(ALICE_BELL_HALF, charlie_x[0])
    circuit.barrier(label="bsm")

    # Bob: deterministic Pauli correction (sigma_x first, then sigma_z)
    with circuit.if_test((charlie_x, 1)):
        circuit.x(BOB_BELL_HALF)
    with circuit.if_test((charlie_z, 1)):
        circuit.z(BOB_BELL_HALF)

    # Bob: projective verification in the token's Pauli basis
    if bob_result is not None:
        rotate_to_computational_basis(circuit, BOB_BELL_HALF, eigenstate.basis)
        if eigenstate.eigenvalue_bit == 1:
            circuit.x(BOB_BELL_HALF)      # relabel so outcome 0 == "matches Alice"
        circuit.measure(BOB_BELL_HALF, bob_result[0])

    return circuit


def build_coherent_teleportation_circuit(
    eigenstate: PauliEigenstate,
    fiber_error: QuantumError | None = None,
) -> QuantumCircuit:
    """
    Deferred-measurement form of the same protocol: Charlie's measurements are
    postponed and Bob's corrections become CX/CZ controlled by q1/q0. By the
    principle of deferred measurement this yields exactly the same reduced
    state on Bob's qubit, but without sampling, so fidelity is exact and
    fully deterministic. Used for the Watchdog's fidelity check.
    """
    circuit = QuantumCircuit(3, name=f"dtpt_coherent_{eigenstate.name}")
    prepare_pauli_eigenstate(circuit, SIGNATURE_QUBIT, eigenstate)
    create_bell_pair(circuit, ALICE_BELL_HALF, BOB_BELL_HALF)
    apply_fiber_channel(circuit, SIGNATURE_QUBIT, fiber_error)
    apply_fiber_channel(circuit, ALICE_BELL_HALF, fiber_error)
    apply_fiber_channel(circuit, BOB_BELL_HALF, fiber_error)
    bell_state_measurement_gates(circuit)
    circuit.cx(ALICE_BELL_HALF, BOB_BELL_HALF)   # pauli_x_correction
    circuit.cz(SIGNATURE_QUBIT, BOB_BELL_HALF)   # pauli_z_correction
    return circuit


# ---------------------------------------------------------------------------
# Exact (noiseless) branch analysis — used by Test 2.2 / 2.3
# ---------------------------------------------------------------------------


def bell_pair_density_matrix() -> DensityMatrix:
    """Exact density matrix of the |Phi+> pair produced by `create_bell_pair`."""
    circuit = QuantumCircuit(2)
    create_bell_pair(circuit, 0, 1)
    return DensityMatrix(Statevector.from_instruction(circuit))


def pauli_correction_operator(broadcast: str) -> Operator:
    """Return Bob's correction operator for a 2-bit "zx" broadcast."""
    if broadcast not in PAULI_CORRECTION_TABLE:
        raise ValueError(f"Invalid BSM broadcast {broadcast!r}; expected one of {VALID_BROADCASTS}.")
    return Operator(PAULI_CORRECTION_TABLE[broadcast])


def apply_pauli_correction(bob_state: DensityMatrix | Statevector, broadcast: str) -> DensityMatrix:
    """
    Apply Bob's correction to an arbitrary single-qubit state.

    Also the entry point for the replay-attack harness: applying a replayed
    broadcast to an unentangled (maximally mixed) qubit leaves it maximally
    mixed, so fidelity with any pure signature state is exactly 0.5.
    """
    rho = bob_state if isinstance(bob_state, DensityMatrix) else DensityMatrix(bob_state)
    return rho.evolve(pauli_correction_operator(broadcast))


def teleport_branch(eigenstate: PauliEigenstate, broadcast: str) -> tuple[float, DensityMatrix]:
    """
    Exact, noiseless evaluation of one BSM branch.

    Projects Charlie's qubits onto outcome `broadcast`, applies Bob's correction,
    and returns (branch_probability, bob_corrected_state). For an ideal channel
    every branch has probability 0.25 and fidelity 1.0.
    """
    if broadcast not in PAULI_CORRECTION_TABLE:
        raise ValueError(f"Invalid BSM broadcast {broadcast!r}; expected one of {VALID_BROADCASTS}.")

    circuit = QuantumCircuit(3)
    prepare_pauli_eigenstate(circuit, SIGNATURE_QUBIT, eigenstate)
    create_bell_pair(circuit, ALICE_BELL_HALF, BOB_BELL_HALF)
    bell_state_measurement_gates(circuit)
    amplitudes = Statevector.from_instruction(circuit).data

    z_bit, x_bit = int(broadcast[0]), int(broadcast[1])
    # Qiskit is little-endian: index = q0*1 + q1*2 + q2*4
    bob_unnormalised = np.array(
        [amplitudes[z_bit + 2 * x_bit + 4 * bob_bit] for bob_bit in (0, 1)], dtype=complex
    )
    branch_probability = float(np.vdot(bob_unnormalised, bob_unnormalised).real)
    bob_state = Statevector(bob_unnormalised / np.sqrt(branch_probability))
    return branch_probability, apply_pauli_correction(bob_state, broadcast)


# ---------------------------------------------------------------------------
# Noisy simulation (qiskit-aer)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TeleportationResult:
    """Deterministic output of one noisy teleportation, consumed by watchdog/fidelity.py."""

    eigenstate: PauliEigenstate
    bob_density_matrix: DensityMatrix
    state_fidelity: float
    depolarizing_probability: float
    amplitude_damping_gamma: float


@dataclass(frozen=True)
class ProjectiveVerificationResult:
    """Sampled output of Bob's projective measurements, consumed by watchdog/thresholds.py."""

    eigenstate: PauliEigenstate
    shots: int
    mismatch_count: int
    bsm_broadcast_counts: dict[str, int] = field(default_factory=dict)

    @property
    def mismatch_rate(self) -> float:
        return self.mismatch_count / self.shots if self.shots else 0.0


def _density_matrix_simulator() -> AerSimulator:
    return AerSimulator(method="density_matrix")


def run_noisy_teleportation(
    eigenstate: PauliEigenstate,
    depolarizing_probability: float = 0.0,
    amplitude_damping_gamma: float = 0.0,
) -> TeleportationResult:
    """
    Exact density-matrix teleportation through the simulated fiber.

    No shot sampling is involved, so the returned `state_fidelity` is fully
    deterministic for fixed noise parameters.
    """
    fiber_error = build_fiber_error(depolarizing_probability, amplitude_damping_gamma)
    circuit = build_coherent_teleportation_circuit(eigenstate, fiber_error)
    circuit.save_density_matrix(qubits=[BOB_BELL_HALF], label="bob_rho")

    result = _density_matrix_simulator().run(circuit, shots=1).result()
    bob_density_matrix = DensityMatrix(result.data(0)["bob_rho"])
    fidelity = float(state_fidelity(bob_density_matrix, eigenstate.statevector))

    return TeleportationResult(
        eigenstate=eigenstate,
        bob_density_matrix=bob_density_matrix,
        state_fidelity=fidelity,
        depolarizing_probability=depolarizing_probability,
        amplitude_damping_gamma=amplitude_damping_gamma,
    )


def run_projective_verification(
    eigenstate: PauliEigenstate,
    shots: int = 1024,
    depolarizing_probability: float = 0.0,
    amplitude_damping_gamma: float = 0.0,
    seed_simulator: int | None = None,
) -> ProjectiveVerificationResult:
    """
    Run the dynamic circuit (real mid-circuit BSM + conditional Paulis) for
    `shots` repetitions and count Bob's projective-measurement mismatches.

    Pass `seed_simulator` for reproducible demo runs.
    """
    if shots <= 0:
        raise ValueError("shots must be positive.")
    fiber_error = build_fiber_error(depolarizing_probability, amplitude_damping_gamma)
    circuit = build_teleportation_circuit(eigenstate, fiber_error, measure_bob=True)

    run_options: dict[str, int] = {"shots": shots}
    if seed_simulator is not None:
        run_options["seed_simulator"] = seed_simulator
    counts: dict[str, int] = _density_matrix_simulator().run(circuit, **run_options).result().get_counts()

    # Count keys are "bob_result charlie_x charlie_z" (registers in reverse order).
    mismatch_count = 0
    bsm_broadcast_counts: dict[str, int] = {b: 0 for b in VALID_BROADCASTS}
    for key, count in counts.items():
        bob_bit, x_bit, z_bit = key.split()
        mismatch_count += count if bob_bit == "1" else 0
        bsm_broadcast_counts[f"{z_bit}{x_bit}"] += count

    return ProjectiveVerificationResult(
        eigenstate=eigenstate,
        shots=shots,
        mismatch_count=mismatch_count,
        bsm_broadcast_counts=bsm_broadcast_counts,
    )


def reduced_bob_state(full_state: Statevector | DensityMatrix) -> DensityMatrix:
    """Trace out Alice's and Charlie's qubits, leaving Bob's single-qubit state."""
    return partial_trace(full_state, [SIGNATURE_QUBIT, ALICE_BELL_HALF])


# ---------------------------------------------------------------------------
# Self-check: `python -m quantum_engine.teleportation`
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    phi_plus = Statevector(np.array([_SQRT_HALF, 0, 0, _SQRT_HALF], dtype=complex))
    bell_fidelity = state_fidelity(bell_pair_density_matrix(), phi_plus)
    print(f"|Phi+> preparation fidelity: {bell_fidelity:.6f}")

    for token in PauliEigenstate:
        branch_fidelities = []
        for broadcast in VALID_BROADCASTS:
            probability, bob_rho = teleport_branch(token, broadcast)
            branch_fidelities.append(state_fidelity(bob_rho, token.statevector))
            assert np.isclose(probability, 0.25), (token, broadcast, probability)
        assert np.allclose(branch_fidelities, 1.0), (token, branch_fidelities)
    print("All 6 eigenstates x 4 broadcasts: branch probability 0.25, fidelity 1.0")

    for p in (0.0, 0.02, 0.10):
        noisy = run_noisy_teleportation(PauliEigenstate.X_PLUS, depolarizing_probability=p)
        print(f"depolarizing p={p:.2f}  ->  F = {noisy.state_fidelity:.4f}")

    verification = run_projective_verification(
        PauliEigenstate.Y_MINUS, shots=1024, depolarizing_probability=0.02, seed_simulator=7
    )
    print(
        f"Projective verification ({verification.eigenstate.value}): "
        f"mismatch_rate = {verification.mismatch_rate:.4f}, BSM counts = {verification.bsm_broadcast_counts}"
    )

    maximally_mixed = DensityMatrix(np.eye(2) / 2)
    replay_fidelity = state_fidelity(apply_pauli_correction(maximally_mixed, "11"), PauliEigenstate.Z_PLUS.statevector)
    print(f"Replayed broadcast on unentangled qubit: F = {replay_fidelity:.4f}")