# Architecture — DTPT Framework

**Project:** Dual-Threshold Projective Teleportation (DTPT) Framework · SIH26141
**Status:** Working prototype, deployed (Render + Vercel). Known gaps are listed in [§9](#9-known-limitations-and-roadmap).

This document describes what the code does today. Anything not yet implemented is marked **Planned**.

---

## 1. What the system is

DTPT is a software simulation of a teleportation-based Quantum Digital Signature (QDS) setting with a deterministic threat-detection layer. It has three parts:

1. **Quantum engine** (Qiskit / Qiskit Aer): teleports single-qubit Pauli-eigenstate tokens through a noisy fiber model and simulates a decoy-state optical channel.
2. **Statistical Watchdog** (NumPy / SciPy): decides accept or abort using fixed physical and statistical bounds. No AI/ML is used anywhere.
3. **Interfaces:** an ETSI GS QKD 014-style REST API (FastAPI) and a React dashboard with an attack simulation panel.

## 2. Topology

Three roles, simulated in one process:

| Role | Function in the code |
|---|---|
| **Alice** (signer, master SAE) | Prepares each token in one of six Pauli eigenstates, chosen by the simulated OQRNG. Holds one half of a Bell pair shared with Bob. |
| **Charlie** (untrusted relay) | Performs the Bell-state measurement (CNOT + H + measure) on Alice's token and Alice's Bell half, then broadcasts 2 classical bits. |
| **Bob** (receiver, slave SAE) | Applies the Pauli correction selected by the broadcast, then measures each token in the claimed basis. |

This is standard quantum teleportation with the Bell-state measurement outsourced to a third party. It is **not** a measurement-device-independent (MDI) or twin-field configuration. In MDI, Charlie measures photons arriving from *both* Alice and Bob. Here Charlie measures two qubits that both originate with Alice.

## 3. Repository layout

```text
backend/
├── main.py                         FastAPI app: CORS, routers, /health, startup cache warm-up
├── pytest.ini                      puts backend/ first on sys.path (see decision_log ADR-012)
├── api/
│   └── etsi_014_routes.py          ETSI 014 routes, mock mTLS, session store, demo simulation route
├── quantum_engine/
│   ├── teleportation.py            Pauli eigenstates, Bell pair, BSM, Pauli corrections, Aer noise
│   ├── oqrng.py                    simulated OQRNG: Poisson source + unbiased extractor
│   └── decoy_states.py             signal/decoy/vacuum modulation, photon-level fiber model, Y1 bound
├── watchdog/
│   ├── fidelity.py                 replay and intercept-resend rules (batch fidelity)
│   ├── decoy_stats.py              photon-number-splitting (PNS) rules
│   ├── thresholds.py               dual-threshold forgery rule, Hoeffding and exact binomial bounds
│   └── attack_simulation_harness.py  session runner, attack injection, ordered Watchdog
└── tests/                          pytest suites (see testing.md)

frontend/                           Vite + React 18 + Tailwind 3.4 + Recharts 3
└── src/
    ├── api.js                      Axios client; interceptor attaches the mock mTLS header per route
    └── components/
        ├── Dashboard.jsx           signature console, attacker panel, Watchdog rule table
        └── Visualizer.jsx          mismatch-rate distribution with s_a / s_v reference lines

docs/                               architecture.md, decision_log.md, THREAT_MODEL.md, testing.md
```

## 4. Request flow

```text
React dashboard (Vercel)
   │  HTTPS + JSON, header X-SSL-Client-Cert-SHA256 on ETSI routes
   ▼
FastAPI (Render)
   ├─ api/etsi_014_routes.py ── authenticate_node()  → 401 / 403
   │        │
   │        ▼
   ├─ watchdog/attack_simulation_harness.py
   │        ├─ quantum_engine/oqrng.py          token selection
   │        ├─ cached Qiskit Aer density matrices (teleportation circuits)
   │        └─ quantum_engine/decoy_states.py   decoy pulse train
   │        ▼
   └─ Watchdog: fidelity.py → decoy_stats.py → thresholds.py
            → VERIFIED (200 + key)  or  ABORT_* (403)
```

## 5. One signature session

`run_signature_session(attack_type, settings)` performs these steps:

1. **Token selection.** The OQRNG picks L = 4096 tokens uniformly from the six Pauli eigenstates.
2. **Quantum channel.** Each token is mapped to Bob's received density matrix. These matrices come from Qiskit Aer density-matrix simulations of the teleportation circuit with a depolarizing + amplitude-damping fiber channel. There are 28 distinct circuits per noise setting (6 honest, 18 intercept-resend, 4 replay), computed once and cached (`lru_cache`).
3. **Signature claim.** The token labels are revealed. In an honest run they are Alice's true labels.
4. **Projective verification.** For each token, Bob's mismatch probability is `1 − ⟨claimed|ρ|claimed⟩` (the Born rule). The outcome is sampled per token, which is O(L).
5. **Decoy channel.** 10⁶ phase-randomised pulses (signal μ = 0.5, decoy ν = 0.1, vacuum) are sent through a photon-level model of 100 km fiber at 0.2 dB/km, detector efficiency 0.8, dark-count probability 10⁻⁶ and misalignment 1.5%.
6. **Telemetry.** The session produces per-token fidelities, mismatch count, decoy statistics, calibrated thresholds and chart data.

Attacks change exactly one ingredient:

| Attack | What changes |
|---|---|
| `INTERCEPT_RESEND` | Eve measures each token in a random Pauli basis on the Alice→Charlie link and resends what she saw. This is modelled as full dephasing in her basis. |
| `REPLAY` | Bob applies a recorded broadcast to a Bell half that no token was teleported into. His state is I/2. |
| `FORGERY` | The channel is untouched. The forger claims random labels because he has no private key. |
| `PNS` | Tokens are untouched. The decoy run uses Eve's photon-number-splitting strategy, tuned to match the honest signal gain. |

## 6. Watchdog (deterministic, ordered)

`evaluate_signature_session()` applies the rules in this order and raises on the first one that fails:

| # | Rule | Condition | Result |
|---|---|---|---|
| 1 | Replay | \|F̄ − 0.5\| ≤ 0.01, where F̄ is the batch-mean fidelity | `ABORT_REPLAY` |
| 2 | Intercept-resend | F̄ ≤ 0.6667 | `ABORT_EAVESDROP` |
| 3 | PNS | Y₁ᴸ ≤ 0, or decoy detections fall outside the exact binomial interval (false alarm ≤ 10⁻⁶) | `ABORT_EAVESDROP` (variant `PNS`) |
| 4 | Forgery | mismatch count ≥ ⌈s_a · L⌉ | `ABORT_FORGERY` |

Notes on the rules:

- Replay is checked before intercept-resend because F = 0.5 also satisfies F ≤ 0.6667.
- Fidelity is averaged over the whole batch. The 2/3 limit is an average, and a single intercepted token can show exactly 0.5.
- Threshold calibration:
  - The honest error rate is e_h = 1 − min F over the six tokens (≈ 0.0294 at p = 0.02).
  - The forger floor is e_f = 1/6, derived from the optimal 1→2 universal cloner.
  - The thresholds split that gap in thirds: s_a = e_h + (e_f − e_h)/3 ≈ 0.0752 and s_v = e_h + 2(e_f − e_h)/3 ≈ 0.1209.
- At L = 4096, the exact probability of accepting a forgery at s_v is about 1.5 × 10⁻¹⁶.

## 7. API

All ETSI routes require the mock mTLS header `X-SSL-Client-Cert-SHA256`. See [§7.1](#71-node-identity-mock-mtls).

| Method | Path | Caller role | Behaviour |
|---|---|---|---|
| GET | `/health` | none | `{"status": "online"}` |
| GET | `/api/v1/keys/{slave_SAE_ID}/status` | SENDER | ETSI status, plus `status_extension.isValid` from the latest session's decoy check |
| POST | `/api/v1/keys/{slave_SAE_ID}/enc_keys` | SENDER | Runs an honest session and returns `key_ID` with status `PENDING` and **no key material** |
| GET | `/api/v1/keys/{master_SAE_ID}/dec_keys?key_ID=…` | RECEIVER | Runs the Watchdog. Returns `200` with the key, or `403` with `{"error": "ABORT_…"}` |
| POST | `/api/v1/simulate/attack` | none (demo) | Body `{"attack_type": "NONE"\|"FORGERY"\|"REPLAY"\|"INTERCEPT_RESEND"\|"PNS"}`. Returns the verdict and chart data, and stores the session so `dec_keys` can be shown returning 403 |

Error codes:

| Code | Cause |
|---|---|
| 400 | The counterpart SAE is not registered with the expected role |
| 401 | Missing or unknown certificate fingerprint |
| 403 | Wrong role for this endpoint, **or** a Watchdog abort |
| 404 | Unknown `key_ID`, or the session belongs to another SAE pair |
| 422 | Request body or parameter validation failed |

Two deliberate deviations from ETSI GS QKD 014:

1. `enc_keys` withholds the key until `dec_keys` passes the Watchdog.
2. DTPT telemetry travels in the ETSI extension fields (`key_container_extension`, `key_extension`, `status_extension`).

### 7.1 Node identity (mock mTLS)

The design assumes a TLS-terminating proxy verifies client certificates and forwards the SHA-256 fingerprint in a header. The prototype skips the TLS layer and checks the header directly against an in-code registry of three demo nodes: `ALICE_SAE_01` (SENDER), `BOB_SAE_01` (RECEIVER) and `CHARLIE_ROUTER_01` (UNTRUSTED_ROUTER). The demo fingerprints are visible in the public frontend bundle. This is a **simulation of mTLS, not mTLS**. See THREAT_MODEL §4.6.

## 8. State, configuration and deployment

**State.** Sessions live in an in-memory, thread-safe `SessionStore` (capacity 500; the oldest session is evicted first). Nothing is persisted. A backend restart (Render redeploys or restarts) clears all sessions, after which old `key_ID`s return 404. Each stored session holds:

- `transaction_id`
- `master_sae_id`, `slave_sae_id`
- `key_size`
- full session telemetry
- `created_at`
- `status` (`PENDING`, `VERIFIED` or `ABORT_*`)

Quantum states are never stored. Only the classical telemetry derived from them is.

**Key material.** On `VERIFIED`, the key is `SHAKE-256(transaction_id ‖ token labels)`, truncated to the requested size (default 256 bits) and base64-encoded. This is a placeholder for the signature payload until message binding (R1) lands.

**Backend environment variables:**

| Variable | Default | Purpose |
|---|---|---|
| `DTPT_KEY_LENGTH` | 4096 | Tokens per signature (L) |
| `DTPT_DEPOLARIZING_P` | 0.02 | Fiber depolarizing parameter |
| `DTPT_AMPLITUDE_DAMPING_GAMMA` | 0.0 | Fiber amplitude damping |
| `DTPT_DECOY_PULSES` | 1000000 | Decoy pulses per session |
| `DTPT_CORS_ORIGINS` | localhost:3000, localhost:5173 | Comma-separated allowed origins |
| `DTPT_ENABLE_ATTACK_SIMULATION` | true | Mounts `/api/v1/simulate` |

Changing any noise parameter recalibrates s_a and s_v automatically.

**Frontend environment variable:** `VITE_API_BASE_URL`. Vite inlines it at build time, so redeploy after changing it.

**Deployment:**

- Backend on Render, free tier. It sleeps after 15 minutes idle; UptimeRobot pings it every 5 minutes.
- Frontend on Vercel.
- Startup warms the Qiskit caches, so each session takes about 0.11 s.

## 9. Known limitations and roadmap

| ID | Limitation | Status |
|---|---|---|
| R1 | No message binding. "Sign Document" does not hash or sign a document. Tokens are not selected by message bits, as they would be in a Gottesman-Chuang construction. | **Planned** |
| R2 | The Watchdog reads fidelity directly from the simulated density matrix. A real receiver must estimate it from measurement statistics on a sacrificed test subset. | **Planned** |
| R3 | The simulated forger guesses blindly (mismatch ≈ 0.5). Thresholds assume an optimal-cloning forger (mismatch ≥ 1/6), who is not yet simulated. | **Planned** |
| R4 | Transferability and non-repudiation between Bob and Charlie are not simulated. Only the Hoeffding repudiation bound is computed. | **Planned** |
| R5 | Single-qubit tokens. The BCGST error-detecting encoding is not implemented (ADR-007). | Accepted |
| R6 | The decoy channel is a photon-level NumPy model that runs alongside the qubit simulation, not inside it (ADR-003). | Accepted |
| R7 | Mock mTLS via a header, with demo fingerprints public in the bundle (ADR-010). | Accepted for demo |
| R8 | In-memory state, lost on restart. | Accepted for demo |
