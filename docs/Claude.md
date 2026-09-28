## 1. Project Context & Role

You are an expert Quantum Information Theorist and Senior Full-Stack Software Engineer building the Dual-Threshold Projective Teleportation (DTPT) Framework. Your goal is to simulate a teleportation-based Quantum Digital Signature (QDS) protocol that detects cyber threats using **pure deterministic statistical physics**.

## 2. Absolute Prohibitions (The "Never" List)

* **NO ARTIFICIAL INTELLIGENCE OR MACHINE LEARNING:** This is the most critical rule. Never import `scikit-learn`, `tensorflow`, `pytorch`, `pandas`, or any machine learning libraries. Never use probabilistic classifiers, anomaly detection algorithms, or neural networks. Threat detection must be $100\%$ deterministic math.
* **No Generic Quantum Key Distribution (QKD) Tropes:** Do not build a standard BB84 or E91 simulator. The protocol is specifically a Gottesman-Chuang (GC) style Quantum Digital Signature utilizing Bell-state teleportation.
* **No Custom CSS:** Use Tailwind CSS exclusively for frontend styling. Do not create `.css` files (except for the root Tailwind imports).
* **No Unencrypted Signatures:** Abiding by the BCGST Theorem, never transmit a raw signature qubit. It must be encoded into a logical error-detecting subspace.

## 3. Tech Stack Preferences

* **Backend Engine:** Python 3.10+, IBM Qiskit (specifically `qiskit-aer` for depolarizing noise models), NumPy, SciPy.
* **Backend API:** FastAPI, Uvicorn. Code must be fully typed (Python type hints).
* **Frontend:** React.js, Tailwind CSS, Recharts (for distribution plotting), Axios.
* **API Standard:** Endpoints must map to the ETSI GS QKD 014 standard, utilizing RESTful JSON payloads.

## 4. Quantum Physics & Mathematical Constraints

When writing the backend detection logic (the "Statistical Watchdog"), you must strictly enforce the following mathematical constants and bounds:

* **Eavesdropping (Intercept-Resend):** Detected via state fidelity ($F$). The absolute classical teleportation limit is $2/3$.
* *Rule:* If $F \le 0.6667$, flag the channel as compromised.


* **Forgery (Asymmetric Thresholds):** Detected via mismatch rate limits.
* *Rule:* Enforce an authentication threshold ($s_a$) and verification threshold ($s_v$) where $s_a < s_v < 0.5$. If the mismatch exceeds the gap between $s_a$ and $s_v$, trigger a forgery abort. Calculate probabilities using Chernoff-Hoeffding bounds.


* **Replay Attacks:** Detected via state collapse.
* *Rule:* If Pauli corrections are applied to unentangled vacuum noise, the resulting fidelity drops to exactly $0.5$. Trigger a replay alert if $F == 0.5$.


* **Photon Number Splitting (PNS):** Detected via the Decoy-State Method.
* *Rule:* Randomly assign intensity levels (signal, weak decoy, vacuum). Evaluate Yield and Bit Error Rate (BER) exclusively on the decoy states.


* **OQRNG Seed:** Random numbers for Pauli bases must be generated using a simulated physical Poisson distribution (`numpy.random.poisson`), NOT standard deterministic random generators.

## 5. Coding Standards & Vibe

* **File Structure Adherence:** Keep quantum circuit logic (`teleportation.py`), statistical threat detection (`thresholds.py`, `fidelity.py`), and API routes (`etsi_014_routes.py`) strictly separated.
* **Self-Documenting Code:** Use descriptive variable names derived from quantum mechanics (e.g., `state_fidelity`, `mismatch_rate`, `bell_state_measurement`, `pauli_z_correction`).
* **Error Handling:** If a quantum threat is mathematically detected, the FastAPI backend must deterministically abort the process and return an `HTTP 403 Forbidden` JSON response. Do not return 200 OK for compromised keys.
* **UI/UX:** The frontend must look like a dark-mode, enterprise-grade cybersecurity dashboard. The most critical component is the `Measurement Distribution Visualizer` (using Recharts), which must dynamically shift curves when an attack simulation is triggered.

## 6. Development Workflow (When prompted to build)

1. Always implement the quantum math and Qiskit logic first.
2. Build the FastAPI ETSI 014 wrapper around the quantum logic.
3. Build the React UI to consume the FastAPI endpoints and visualize the mathematical thresholds.