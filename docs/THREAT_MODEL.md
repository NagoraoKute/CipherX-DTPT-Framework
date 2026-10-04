# Threat Model — DTPT Framework

**Scope.** The threats the prototype simulates and detects, the exact rule each one triggers, and what is *not* covered. Every detection is a fixed comparison against a physical or statistical bound. No AI/ML is used.

---

## 1. Assets

| Asset | Status in the prototype |
|---|---|
| **Unforgeability:** nobody without Alice's private token labels can produce a signature Bob accepts | Implemented: dual-threshold mismatch rule |
| **Channel integrity:** tampering with the quantum channel is detected | Implemented: fidelity rules and decoy-state rules |
| **Message binding:** the signature is tied to a specific document | **Not implemented** (roadmap R1) |
| **Non-repudiation and transferability:** a signature Bob accepts will also be accepted by Charlie, so Alice cannot disown it | **Not implemented**; only the repudiation probability bound is computed (roadmap R4) |
| **Key confidentiality at the API:** key material is released only to the registered receiver | Implemented with mock mTLS plus a per-session ownership check |

## 2. Adversaries

| Actor | Capabilities assumed |
|---|---|
| **Eve** (external) | Full access to the fiber. Can measure and resend qubits, record classical broadcasts, and split photons from multi-photon pulses. |
| **Malicious Charlie** (relay) | Sees all broadcasts; can replay or alter them. |
| **Forger** (e.g., a malicious Bob trying to sign as Alice) | No access to Alice's private token labels. |
| **Classical attacker** | Can call the REST API directly. |

## 3. Detected attacks

### 3.1 Intercept-resend (eavesdropping)

- **Attack.** Eve measures each token on the Alice→Charlie link in a basis she picks at random from X, Y, Z, then resends the eigenstate she observed.
- **Physics.** No measure-and-prepare strategy can achieve an average fidelity above 2/3 for unknown qubit states. Against our six-state alphabet, Eve picks the right basis one time in three (F = 1) and the wrong one two times in three (F = 0.5). The average is exactly 2/3, which Qiskit reproduces.
- **Rule.** Batch-mean fidelity F̄ ≤ 0.6667 → `ABORT_EAVESDROP`.
- **Measured.** F̄ ≈ 0.657 with fiber noise. Correctly labelled in 399 of 400 sessions at L = 4096; the remaining session was still aborted, as `ABORT_FORGERY`.

### 3.2 Replay

- **Attack.** A recorded 2-bit broadcast is replayed. Bob applies the Pauli correction to a Bell half that no token was ever teleported into.
- **Physics.** Teleportation consumes the shared entanglement. Bob's qubit is maximally mixed (I/2), and its fidelity with any pure state is exactly 1/2. Pauli corrections leave I/2 unchanged.
- **Rule.** \|F̄ − 0.5\| ≤ 0.01 → `ABORT_REPLAY`. This is checked *before* the intercept-resend rule, because 0.5 ≤ 0.6667.
- **Measured.** F̄ = 0.5000; detected in 400 of 400 sessions.

### 3.3 Photon number splitting (PNS)

- **Attack.** Eve counts photons in each pulse without disturbing them. She blocks single-photon pulses, keeps one photon from each multi-photon pulse, and forwards the rest losslessly. She forwards just enough pulses to match the honest **signal** gain. Token fidelity is untouched, so the fidelity rules cannot see this attack.
- **Physics.** Weak decoy pulses contain far fewer multi-photon events than signal pulses, so Eve cannot match the decoy gain at the same time.
- **Rules.**
  - Y₁ᴸ ≤ 0 (Ma-Qi-Zhao-Lo lower bound on the single-photon yield), **or**
  - decoy detections outside an exact binomial acceptance interval (honest false-alarm probability ≤ 10⁻⁶).
  - Either one → `ABORT_EAVESDROP`, variant `PNS`.
- **Measured.** Decoy detections fall about 4× below expectation and Y₁ᴸ goes negative; detected in 400 of 400 sessions.

### 3.4 Forgery

- **Attack.** The forger presents token labels without knowing Alice's private ones. Currently simulated as **blind guessing**, which gives a per-token mismatch probability of 1/2.
- **Physics.** Non-orthogonal states cannot be perfectly distinguished or cloned. The thresholds assume a stronger forger that clones optimally, with mismatch ≥ 1/6.
- **Rule.** Mismatch count ≥ ⌈s_a · L⌉ → `ABORT_FORGERY`. At L = 4096 and p = 0.02, s_a ≈ 7.5% and s_v ≈ 12.1%.
- **Measured.**
  - Blind forgeries land at about 50% mismatch: detected in 400 of 400.
  - Honest sessions land at about 3%: no false aborts in 400.
  - The exact probability that a cloning-level forger is accepted at s_v is about 1.5 × 10⁻¹⁶.
- **Gap.** The cloning forger itself is not yet simulated (roadmap R3).

### 3.5 API impersonation

- **Attack.** An attacker calls the ETSI endpoints directly to obtain keys.
- **Rules.**
  - Unknown or missing certificate fingerprint → 401.
  - Registered node calling an endpoint its role does not allow → 403.
  - A session that does not belong to the caller's SAE pair → 404 (its existence is not revealed).
  - Any Watchdog abort → 403. Key material is never serialised for an aborted session.

## 4. Known weaknesses

1. **Fidelity is read from the simulated density matrix.** A real receiver must estimate F from measurement outcomes on a sacrificed test subset (roadmap R2).
2. **Blind forger only.** See §3.4 (roadmap R3).
3. **No message binding, non-repudiation or transferability.** See §1 (roadmap R1, R4).
4. **Single-qubit tokens.** The BCGST encoding needed to authenticate quantum states is not implemented (ADR-007).
5. **Decoy and qubit layers are separate models** of the same fiber (ADR-003).
6. **Mock mTLS.** Identity is a header value, and the demo fingerprints ship in the public frontend bundle. Anyone can impersonate Alice or Bob against the deployed demo. Real deployments must verify client certificates in the TLS handshake (ADR-010).
7. **Simulated entropy.** The OQRNG is pseudo-random underneath (ADR-005).

## 5. Out of scope

These are not modelled, so no claim is made about them:

- Detector side channels (blinding, time-shift, efficiency mismatch). The topology is not MDI (ADR-002).
- Trojan-horse attacks on the source, and laser seeding.
- Collective and coherent attacks beyond the per-token intercept-resend and cloning models.
- Finite-key effects on the decoy estimates beyond the binomial interval.
- Denial of service, including an adversary who simply blocks the channel. Aborting is the expected outcome, not a defence.
- Compromise of the server, the frontend host or the demo node registry.
