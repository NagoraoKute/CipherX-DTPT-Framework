### `DATA_MODEL.md`

# Data & Security Model: DTPT Framework

**Version:** 1.0

**Context:** This document outlines the data schema, data states, and Row Level Security (RLS) policies for the classical software layer managing the quantum telecommunication hardware.

## 1. Data Sensitivity Classification

In a teleportation-based QDS system, data exists in both classical and quantum states. Strict separation is required.

* **Ephemeral Quantum Data (Never Stored):** Density matrices ($\rho$), raw qubits, and live wave functions. These exist only in transit and during the Qiskit simulation's execution.
* **Private Classical Data (Secured at Rest):** OQRNG Poisson seeds, the original hashed document, and the `public_key_matrix` (Pauli bases).
* **Public Classical Data (In Transit):** The 2-bit classical broadcast from the Bell-State Measurement (BSM). This data is useless to an attacker without the entangled counterpart.

## 2. Database Schema (Classical Post-Processing)

### Table: `NodeRegistry`

Stores the cryptographic identity of trusted nodes (Alice, Bob) on the network.

| Column | Type | Constraints | Description |
| --- | --- | --- | --- |
| `node_id` | UUID | Primary Key | Unique identifier for the enterprise user/proxy. |
| `role` | String | Not Null | `SENDER`, `RECEIVER`, `UNTRUSTED_ROUTER` |
| `public_key_matrix` | JSON | Not Null | Pre-registered Pauli X and Z bases. |
| `tls_cert_hash` | String | Unique | Used for mTLS ETSI 014 API authentication. |

### Table: `SignatureLogs`

Stores the mathematical outcomes of the projective measurements for audit and verification.

| Column | Type | Constraints | Description |
| --- | --- | --- | --- |
| `transaction_id` | UUID | Primary Key | Maps to the specific digital signature request. |
| `sae_id` | UUID | Foreign Key | The Secure Application Entity requesting verification. |
| `mismatch_rate` | Float | Not Null | The error rate calculated during Pauli projective measurement. |
| `state_fidelity` | Float | Not Null | The $F$ score of the received density matrix. |
| `status` | String | Not Null | `VERIFIED`, `ABORT_FORGERY`, `ABORT_EAVESDROP`, `ABORT_REPLAY`. |
| `timestamp` | Datetime | Default Now() | Time of classical broadcast. |

### Table: `DecoyTelemetry`

Logs the transmission properties for the Decoy-State method to detect PNS attacks.

| Column | Type | Constraints | Description |
| --- | --- | --- | --- |
| `transaction_id` | UUID | Foreign Key | Links to `SignatureLogs`. |
| `yield_rate` | Float | Not Null | Fraction of decoy pulses successfully received. |
| `ber_decoy` | Float | Not Null | Bit Error Rate calculated *only* on decoy states. |

## 3. Row Level Security (RLS) & API Access Control

The framework utilizes the **ETSI GS QKD 014** standard for key delivery, which mandates strict access controls.

* **mTLS Authentication:** All API requests must be signed with mutual TLS. If `tls_cert_hash` does not match the requesting `node_id`, the API drops the connection.
* **RLS Policy - `SignatureLogs`:** A node (e.g., a Web3 Smart Contract application) can only `SELECT` rows where `sae_id == requesting_node_id`. Nodes cannot query the error rates or fidelity scores of transactions that do not belong to them.
* **Data Masking:** `public_key_matrix` is never returned via the `GET /api/v1/keys/{sae_id}/status` endpoint; the API only returns a boolean `isValid` flag and the verified signature payload.

---
