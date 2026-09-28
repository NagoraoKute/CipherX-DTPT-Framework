# Technical Design Document: DTPT Framework

**Project:** Dual-Threshold Projective Teleportation (DTPT) Framework (SIH26141)

**Version:** 1.0

## 1. System Architecture Overview

The DTPT Framework is a Software-Defined Quantum Threat Detection system. It operates on a decentralized, 3-node Measurement-Device-Independent (MDI) topology.

* **Alice (Sender/Signer):** Encodes the signature via Pauli eigenstates into a logical error-detecting subspace.
* **Charlie (Untrusted Router):** Performs the Bell-State Measurement (BSM) to teleport the state.
* **Bob (Receiver/Verifier):** Applies Pauli corrections and projective measurements.

The software stack separates the **Quantum Simulation Engine** from the **Enterprise API**, allowing classical web applications to securely request quantum signatures via ETSI-standardized REST protocols.

### 1.1. High-Level Architecture Diagram

[ React.js Frontend (User UI & Dashboard) ]
│      ▲
│      │ (JSON / HTTP Status Codes)
▼      │
[ FastAPI Backend (ETSI GS QKD 014 REST API) ]
│      ▲
│      │ (Raw Outcome Arrays & Statevectors)
▼      │
[ Statistical Watchdog (NumPy/SciPy) ] ◄─── Evaluates thresholds (Fidelity, s_a, s_v)
│      ▲
│      │ (Density Matrices & Measurement Bits)
▼      │
[ IBM Qiskit Engine ] ◄─── Executes Bell States, Pauli Gates, & Decoy States

## 2. Component Structure

### 2.1. Frontend (React.js + Tailwind CSS + Recharts)

* **Signature Console Component:** The primary interface for initiating a signature transaction. Displays the current status of the quantum channel.
* **Attack Simulation Harness:** A control panel exclusively for the hackathon demonstration. Contains buttons to inject Forgery, Replay, and Intercept-Resend (Eavesdropping/PNS) attacks into the backend Qiskit simulation.
* **Measurement Distribution Visualizer:** A live line/area chart (via Recharts). It listens for data arrays from the backend and plots the Pauli measurement mismatch distribution, visualizing the curve shifting past the static $s_a$ and $s_v$ threshold lines during an attack.

### 2.2. Backend (FastAPI)

* **`etsi_014_routes.py`:** Handles external classical requests. Enforces mutual TLS (mTLS) for node authentication.
* **`teleportation.py`:** The core IBM Qiskit circuit. Generates the 3-qubit topology, applies depolarizing noise (`qiskit_aer`), and executes the CNOT/Hadamard BSM.
* **`decoy_states.py`:** Modulates the intensity of transmitted pulses to interleave signal states, weak decoy states, and vacuum states.
* **`watchdog/` (Threat Detection):** Purely mathematical modules that ingest Qiskit outputs and deterministically evaluate them against physical limits (Zero AI/ML).

## 3. Database & State Schema

For the hackathon prototype, a lightweight SQLite or in-memory dictionary is sufficient. We only need to store active node registries and the telemetry logs for the distribution visualizer.

**Table: `SignatureLogs**`

* `transaction_id` (UUID, Primary Key)
* `sae_id` (String) - The ID of the Secure Application Entity requesting the signature.
* `mismatch_rate` (Float) - The calculated error rate for the specific signature.
* `state_fidelity` (Float) - The calculated fidelity ($F$) of the received density matrix.
* `status` (String) - Enum: `[VERIFIED, ABORTED_FORGERY, ABORTED_EAVESDROPPING, ABORTED_REPLAY]`
* `timestamp` (Datetime)

**Table: `NodeRegistry**`

* `node_id` (String, Primary Key) - The cryptographic identity of the proxy/user.
* `public_key_matrix` (String) - The pre-registered Pauli bases.

## 4. API Endpoints (ETSI GS QKD 014 Compliant)

The API strictly follows ETSI protocols for quantum key delivery.

### 4.1. Core Quantum Routes

* **`POST /api/v1/keys/{sae_id}/enc_keys`**
* *Description:* Initiates the teleportation-based signature generation. Triggers the Qiskit engine.
* *Response:* Returns a transaction ID and a status of `PENDING`.


* **`GET /api/v1/keys/{sae_id}/status`**
* *Description:* Checks if the quantum channel is currently free of eavesdroppers (evaluates recent Decoy-State BER).


* **`GET /api/v1/keys/{sae_id}/dec_keys`**
* *Description:* Retrieves the verified signature key.
* *Security Constraint:* The API will ONLY return a `200 OK` if the Watchdog confirms $F > 0.6667$ and mismatch $< s_a$. Otherwise, it returns `403 FORBIDDEN`.



### 4.2. Hackathon Specific Routes (Attack Simulation)

* **`POST /api/v1/simulate/attack`**
* *Payload:* `{ "attack_type": "FORGERY" | "REPLAY" | "INTERCEPT_RESEND" }`
* *Description:* Injects targeted mathematical noise or classical interception into the Qiskit circuit to demonstrate the Watchdog's detection capabilities. Returns the shifted distribution arrays for the frontend Recharts visualizer.



## 5. Security & Threat Detection Thresholds (The Math Layer)

The architecture embeds physical constraints directly into the classical post-processing layer:

1. **OQRNG Seed Constraint:** Pauli bases must be selected using `numpy.random.poisson(lam)`. Standard `math.random` is prohibited.
2. **Intercept-Resend Bound:**
* `if state_fidelity <= 0.6667: raise EavesdroppingException()`


3. **No-Cloning Bound:**
* `if state_fidelity == 0.5000: raise ReplayAttackException()`


4. **Asymmetric Mismatch Bound (Gottesman-Chuang):**
* Variables `s_a` and `s_v` are calculated dynamically via Chernoff-Hoeffding bounds for the given key length $n$.
* `if mismatch_rate >= s_a: raise ForgeryException()`



## 6. Deployment & Execution

* **Local Development:** Run via `uvicorn main:app --reload` (Backend) and `npm start` (Frontend).
* **Dependencies:** Requirements mapped in `requirements.txt` (Backend) and `package.json` (Frontend).
* **Scalability:** Because threat detection is $O(N)$ linear time (pure algebra instead of machine learning tensors), the Watchdog can process thousands of quantum signatures per second on standard commercial CPU hardware.