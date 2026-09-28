

## Dual-Threshold Projective Teleportation (DTPT) Framework

The Dual-Threshold Projective Teleportation (DTPT) Framework is a deterministic, AI-free software architecture designed to secure teleportation-based Quantum Digital Signatures (QDS).

Moving beyond classical cryptographic assumptions, this framework relies entirely on **Information-Theoretic Security (ITS)** guaranteed by the laws of quantum mechanics. We explicitly avoid the use of Artificial Intelligence or Machine Learning. Instead, our detection layer utilizes **Gottesman-Chuang (GC) style QDS modeling**, Pauli eigenstates, projective measurements, and rigorous statistical analysis of measurement outcomes to detect threats.

To protect against Photon Number Splitting (PNS) attacks inherent in real-world telecommunications, the framework integrates the **Decoy-State Method**, utilizing simulated Optical Quantum Random Number Generator (OQRNG) seeds to mix signal and decoy states.

## 🧠 The Threat Detection Matrix (Zero AI)

Our framework identifies the four mandated cyber threats using pure quantum statistical physics evaluated via our custom **Attack Simulation Harness**:

1. **Eavesdropping (Quantum Channel Manipulation):** Detected via *State Fidelity Degradation*. An intercept-resend attack forces wave-function collapse. The framework calculates the state fidelity ($F$) of the recovered signature. If $F \le 66.7\%$, the channel is flagged as compromised.
2. **Forgery:** Detected via *Asymmetric Mismatch Thresholds*. The framework replaces legacy symmetrization with a mathematical gap evaluated via Chernoff-Hoeffding bounds. We enforce $s_a < s_v < 0.5$ (where $s_a$ is authentication and $s_v$ is verification). Any forged signature mathematically exceeds this threshold gap.
3. **Replay Attacks:** Detected via *No-Cloning State Collapse*. Teleportation strictly consumes the pre-shared Bell state. If classical transmission bits are replayed, Pauli corrections apply to vacuum noise, causing state fidelity to crash to exactly 50%.
4. **Impersonation:** Detected via *Measurement Distribution Visualization*. The framework uses ETSI GS QKD 014 REST APIs with mutual TLS (mTLS). Unauthorized nodes attempting to bypass proxy authorization cause severe distribution shifts in the Pauli measurement outcomes, which are instantly visualized and rejected.

## 🏗️ Tech Stack

* **Quantum Simulation Engine:** IBM Qiskit (using `qiskit-aer` for realistic depolarizing noise models)
* **Statistical Physics Engine:** Python (NumPy, SciPy)
* **Enterprise API Layer:** FastAPI (RESTful ETSI 014 compliance)
* **Frontend Dashboard:** React.js / Tailwind CSS

## 📁 Repository Structuretext

SIH-DTPT-Framework/
├── frontend/                  # React UI for signature execution & visualization
├── backend/
│   ├── api/                   # FastAPI ETSI GS QKD 014 REST endpoints
│   ├── quantum_engine/
│   │   ├── teleportation.py         # Bell-State generation & Pauli corrections
│   │   ├── decoy_states.py          # Decoy & Signal state modulation
│   │   └── distribution_visualizer.py # Plots Poisson distributions & threshold shifts
│   ├── watchdog/
│   │   ├── attack_simulation_harness.py # Simulates Forgery, Replay, & PNS attacks
│   │   ├── fidelity.py              # Enforces the F > 66.7% limit
│   │   └── thresholds.py            # Enforces the bounds
│   └── main.py
├── docs/
│   ├── TRD.md                 # Technical Requirements Document
│   └── DTPT_Architecture.png
└── README.md

```

## 📊 The "Winning" Demo: Measurement Distribution Visualization
Our primary demonstration features the **Measurement Distribution Visualizer**. 
When running the `attack_simulation_harness.py`, the frontend visualizes the Pauli measurement outcome distribution. Under normal operation, the mismatch rate remains safely below the $s_a$ limit. When the judge clicks "Execute Forgery Attack," the UI explicitly visualizes the measurement distribution curve shifting violently to the right, crossing the $s_v$ limit and triggering an immediate, mathematically proven protocol abort.

## ⚙️ How to Run the Prototype
**1. Start the Quantum Backend:**
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

```

**2. Start the Visualization Frontend:**

```bash
cd frontend
npm install
npm start

```

```

```