# Testing Strategy: DTPT Framework

**Version:** 1.0

**Context:** This document outlines the critical-path test coverage and execution instructions for the Dual-Threshold Projective Teleportation (DTPT) Framework. Tests are designed to verify deterministic quantum mechanics and statistical mathematics. **No AI/ML testing libraries are permitted.**

## 1. Testing Philosophy & Critical Paths

Because this framework guarantees Information-Theoretic Security (ITS), testing focuses on proving the mathematical boundaries:

1. **Quantum State Integrity:** Verifying IBM Qiskit correctly constructs the Bell-State Measurement (BSM) and Pauli corrections.
2. **Watchdog Determinism:** Proving the framework strictly enforces the $F \le 0.6667$ (eavesdropping) and $s_a < s_v < 0.5$ (forgery) limits without false negatives.
3. **API Security:** Ensuring compromised keys are permanently blocked (HTTP 403) from external classical systems.

## 2. Test Execution

**Backend (Python/FastAPI/Qiskit)**
We use `pytest` for all backend unit and integration testing.

```bash
cd backend
pip install pytest httpx
pytest tests/ -v

```

**Frontend (React)**
We use `Jest` and `@testing-library/react`.

```bash
cd frontend
npm run test

```

---

## 3. Phase-by-Phase Testing Guide

### Phase 1: Environment & Initialization

**Goal:** Verify basic communication and environment health.

* **Test 1.1 (Backend):** `test_health_check.py`
* *Action:* Send `GET /health` to FastAPI.
* *Assertion:* Expect `200 OK` and `{"status": "online"}`.


* **Test 1.2 (Frontend):** `App.test.js`
* *Action:* Render the main Dashboard component.
* *Assertion:* Expect the "Sign Document" button to be in the DOM.



### Phase 2: Quantum Engine

**Goal:** Verify Qiskit circuits and OQRNG physical entropy logic.

* **Test 2.1 (OQRNG Generator):** `test_oqrng.py`
* *Action:* Generate an array of 1,000 basis selections.
* *Assertion:* Ensure the output strictly follows `numpy.random.poisson` distribution limits, not a uniform pseudo-random distribution.


* **Test 2.2 (Bell-State Creation):** `test_teleportation.py`
* *Action:* Run the CNOT and Hadamard gate sequence in Qiskit `StatevectorSimulator`.
* *Assertion:* Verify the output density matrix represents a perfect $\vert{}\Phi^+\rangle$ entangled state before noise is applied.


* **Test 2.3 (Pauli Corrections):** `test_teleportation.py`
* *Action:* Mock the 4 possible classical 2-bit broadcasts (00, 01, 10, 11).
* *Assertion:* Verify Bob's logic perfectly applies $I$, $\sigma_x$, $\sigma_z$, and $\sigma_z\sigma_x$ respectively.



### Phase 3: Statistical Watchdog (CRITICAL PATH)

**Goal:** Verify the deterministic math boundaries. These tests prove to the judges that the system works without AI.

* **Test 3.1 (Eavesdropping / Intercept-Resend):** `test_fidelity.py`
* *Action:* Mock a state fidelity score of `0.65`.
* *Assertion:* Expect `EavesdroppingException` to be raised (since $0.65 \le 0.6667$).


* **Test 3.2 (Replay Attack):** `test_fidelity.py`
* *Action:* Mock a state fidelity score of `0.5000` (measuring unentangled vacuum noise).
* *Assertion:* Expect `ReplayAttackException` to be raised.


* **Test 3.3 (Forgery / Mismatch Bounds):** `test_thresholds.py`
* *Action:* Set $s_a = 0.05$ and $s_v = 0.08$. Mock a signature mismatch rate of `0.07`.
* *Assertion:* Expect `ForgeryException` to be raised (since $0.07 > s_a$).


* **Test 3.4 (PNS Attack / Decoys):** `test_decoy_stats.py`
* *Action:* Inject statistical variance into the mocked decoy-state Bit Error Rate (BER).
* *Assertion:* Expect `PNSAttackException` to be raised when variance exceeds the physical fiber-optic baseline.



### Phase 4: API & Enterprise Integration

**Goal:** Verify ETSI GS QKD 014 compliance and security blocking.

* **Test 4.1 (Authorized Key Delivery):** `test_etsi_routes.py`
* *Action:* Mock a successful Watchdog pass (Fidelity = 0.99, Mismatch = 0.01). Request `GET /api/v1/keys/{sae_id}/dec_keys`.
* *Assertion:* Expect `200 OK` and a valid JSON signature payload.


* **Test 4.2 (Threat Blocking):** `test_etsi_routes.py`
* *Action:* Mock a failed Watchdog check (Fidelity = 0.60). Request the same key retrieval endpoint.
* *Assertion:* Expect `403 Forbidden` with payload `{"error": "ABORT_EAVESDROP"}`. *Crucial: The compromised key must never be returned.*


* **Test 4.3 (Node Impersonation):** `test_security.py`
* *Action:* Send a request with a mocked `tls_cert_hash` that is not in the `NodeRegistry`.
* *Assertion:* Expect `401 Unauthorized` / connection dropped.



### Phase 5: Frontend Interaction

**Goal:** Verify the UI triggers the correct backend simulations and dynamically updates.

* **Test 5.1 (Attack Simulation Harness UI):** `Dashboard.test.js`
* *Action:* Click the "Execute Forgery Attack" button.
* *Assertion:* Verify an Axios `POST /api/v1/simulate/attack` request is dispatched with `{ "attack_type": "FORGERY" }`.


* **Test 5.2 (Measurement Distribution Visualizer):** `Visualizer.test.js`
* *Action:* Pass a mocked array of high-mismatch values (simulating a forgery) into the Recharts component.
* *Assertion:* Verify the charted curve renders past the static `<ReferenceLine x={s_v} />` SVG element.