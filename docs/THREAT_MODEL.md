### `THREAT_MODEL.md`

# Threat Model & Attack Surface: DTPT Framework

**Version:** 1.0

**Context:** This document outlines the specific cyber threats targeting teleportation-based Quantum Digital Signatures (QDS) and the deterministic physics/math constraints utilized by the framework to neutralize them without the use of Artificial Intelligence.

## 1. Protected Assets

1. **Signature Non-Repudiation:** Ensuring a sender (Alice) cannot deny signing a document.
2. **Signature Unforgeability:** Ensuring a receiver (Bob) or router (Charlie) cannot alter a signature.
3. **Quantum Channel Integrity:** Ensuring no external entity can observe the quantum transmission.

## 2. Threat Actor Profiles

* **Eve (The Eavesdropper):** An external attacker with access to the physical fiber-optic cables attempting to read the signature in transit.
* **Malicious Charlie (The Untrusted Router):** A compromised telecom hub attempting to alter the Bell-State Measurements.
* **Malicious Bob (The Forger):** The intended receiver attempting to alter the signature document post-transmission.

## 3. Attack Vectors & Deterministic Mitigations

### 3.1. Intercept-Resend Attack (Eavesdropping)

* **Attack Vector:** Eve intercepts the quantum signal, measures it, and sends a new qubit to Bob based on her classical measurement.
* **Physical Mitigation:** Wave-function collapse (Heisenberg's Uncertainty Principle).
* **Mathematical Software Lock:** The maximum average fidelity of a classical guess is $2/3$. The Watchdog evaluates the state vector. **If $F \le 0.6667$, trigger `ABORT_EAVESDROP`.**

### 3.2. Photon Number Splitting (PNS) Attack

* **Attack Vector:** Eve exploits multi-photon emissions from weak coherent lasers by splitting one photon off to keep and letting the rest pass to Bob undetected (bypassing the fidelity drop).
* **Physical Mitigation:** Decoy-State Method.
* **Mathematical Software Lock:** Alice interleaves random decoy and vacuum states. Eve unknowingly interacts with the decoys. The Watchdog isolates the decoy transmission data. **If `ber_decoy` deviates from the physical baseline variance, trigger `ABORT_EAVESDROP`.**

### 3.3. Forgery / Symmetrization Breach

* **Attack Vector:** Malicious Bob or Charlie attempts to guess the Pauli eigenstates to forge Alice's signature for a new document. Because the states are non-orthogonal, perfect discrimination is impossible.
* **Physical Mitigation:** Gottesman-Chuang QDS modeling (Quantum states as one-way functions).
* **Mathematical Software Lock:** The Watchdog calculates the projective mismatch rate. **If `mismatch_rate` is not strictly bounded by $s_a < s_v < 0.5$, trigger `ABORT_FORGERY`.**

### 3.4. Replay Attack

* **Attack Vector:** Eve records the classical 2-bit broadcast from Charlie's BSM and replays it later to force Bob to authenticate a past transaction.
* **Physical Mitigation:** The No-Cloning Theorem. Teleportation inherently consumes the shared Bell state.
* **Mathematical Software Lock:** Bob's Pauli gates ($X$, $Z$) will apply to unentangled vacuum noise. The resulting measurement yields pure randomness. **If state fidelity $F == 0.5000$, trigger `ABORT_REPLAY`.**

### 3.5. API Impersonation (Classical Attack)

* **Attack Vector:** An attacker bypasses the quantum channel entirely and attempts to query the backend REST API directly to retrieve verified keys.
* **Software Mitigation:** Strict ETSI GS QKD 014 compliance. The FastAPI backend requires valid mTLS certificates mapped to the `NodeRegistry`. Unregistered requests receive an `HTTP 403 Forbidden` response.