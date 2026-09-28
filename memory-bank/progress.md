# Project Progress: DTPT Framework (SIH26141)

## Current Status: PHASE 1 (Initialization)

**Phase 1 Goal:** Set up repository, frontend, and backend environments.

### 📝 Roadmap Tracker

* [x] **Phase 0: Planning & Documentation**
* [x] Finalize Project PRD
* [x] Create Technical Design Document
* [x] Setup AI Instructions (CLAUDE.md / .cursorrules)
* [x] Setup Memory Bank


* [ ] **Phase 1: Initialization**
* [ ] Initialize Git repository
* [ ] Setup FastAPI backend (`requirements.txt`, `main.py`)
* [ ] Setup React frontend (`npx create-react-app`, Tailwind, Recharts)


* [ ] **Phase 2: Quantum Engine (Backend)**
* [ ] Build `oqrng.py` (Poisson distribution seed)
* [ ] Build `decoy_states.py` (Intensity modulation)
* [ ] Build `teleportation.py` (Qiskit Bell-states & Pauli corrections)


* [ ] **Phase 3: Statistical Watchdog (Backend)**
* [ ] Build `fidelity.py` (66.67% bound check)
* [ ] Build `thresholds.py` (s_a < s_v < 0.5 mismatch gap check)
* [ ] Build `attack_simulation_harness.py`


* [ ] **Phase 4: API Integration**
* [ ] Build `etsi_014_routes.py`
* [ ] Connect Watchdog logic to return 403 Forbidden on attacks


* [ ] **Phase 5: Frontend Dashboard**
* [ ] Build Signature Console UI
* [ ] Build Attacker Control Panel (Simulate Forgery, Replay, PNS)
* [ ] Build Measurement Distribution Visualizer (Recharts)


* [ ] **Phase 6: Final Testing & Demo Prep**
* [ ] End-to-end testing
* [ ] Rehearse Presentation



---

### 2. `memory-bank/architecture.md`

This file reminds the AI of the system topology and the strict mathematical rules it must enforce.

# Architecture Core: DTPT Framework

**Topology:** 3-Node Measurement-Device-Independent (MDI) Network.

* **Alice (Sender):** Encodes signature in error-detecting subspace (BCGST Theorem). Generates decoy states.
* **Charlie (Untrusted Router):** Executes Bell-State Measurement (BSM).
* **Bob (Receiver):** Executes Pauli corrections based on classical broadcast bits and projective measurements.

## The Mathematical Threat Detection Matrix (Zero AI)

*The system MUST evaluate these deterministic limits during classical post-processing.*

1. **Eavesdropping (Intercept-Resend):**
* **Metric:** State Fidelity ($F$) extracted from density matrix.
* **Condition:** If $F \le 0.6667$, abort protocol (Classical teleportation limit).


2. **Forgery (Gottesman-Chuang Asymmetric Bounds):**
* **Metric:** Projective Measurement Mismatch Rate.
* **Condition:** Enforce $s_a < s_v < 0.5$. If mismatch rate $\ge s_a$, abort protocol.


3. **Replay Attack:**
* **Metric:** Unentangled State Collapse.
* **Condition:** If classical bits are replayed over vacuum noise, $F == 0.5000$. Abort protocol.


4. **Photon Number Splitting (PNS):**
* **Metric:** Decoy-State Yield & Bit Error Rate (BER).
* **Condition:** If variance in decoy transmission properties deviates from expected physical baseline, abort protocol.



## Component Flow

`React Frontend` <--(JSON)--> `FastAPI (ETSI 014)` <--(NumPy/SciPy Math)--> `Qiskit Engine`

---

### 3. `memory-bank/tech-stack.md`

This file sets the hard constraints for libraries and tools. It prevents the AI from hallucinating or importing unauthorized libraries (like Machine Learning tools).

# Tech Stack & Constraints: DTPT Framework

## Absolute Prohibitions (CRITICAL)

* **NO AI OR MACHINE LEARNING:** Do not import `scikit-learn`, `tensorflow`, `pytorch`, `pandas`, `xgboost`, or any ML/AI libraries.
* **NO PROBABILISTIC HEURISTICS:** All threat detection must use 100% deterministic algebra, physics-based formulas, and statistical limits (e.g., Chernoff-Hoeffding bounds).
* **NO CUSTOM CSS FILES:** Use Tailwind CSS utility classes exclusively.

## Backend (Quantum Simulation & API)

* **Language:** Python 3.10+
* **Quantum Simulator:** `qiskit`
* **Noise Modeling:** `qiskit-aer` (must be used to simulate depolarizing fiber-optic noise)
* **Statistical Math:** `numpy` (specifically `numpy.random.poisson` for OQRNG), `scipy` (for matrix algebra)
* **Web API:** `fastapi`, `uvicorn`, `pydantic` (for type checking and ETSI GS QKD 014 routing)

## Frontend (Dashboard & Visualization)

* **Framework:** React.js (Create React App or Vite)
* **Styling:** Tailwind CSS
* **Data Visualization:** `recharts` (Used strictly for the Measurement Distribution Visualizer to show distribution curve shifts during the attack simulation).
* **API Client:** `axios`

