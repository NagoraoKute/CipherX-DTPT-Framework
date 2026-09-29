## Dual-Threshold Projective Teleportation (DTPT) Framework

The Dual-Threshold Projective Teleportation (DTPT) Framework is a deterministic, AI-free software architecture designed to secure teleportation-based Quantum Digital Signatures (QDS). 

Moving beyond classical cryptographic assumptions, this framework relies entirely on **Information-Theoretic Security (ITS)** guaranteed by the laws of quantum mechanics. We explicitly avoid the use of Artificial Intelligence or Machine Learning. Instead, our detection layer utilizes **Gottesman-Chuang (GC) style QDS modeling**, Pauli eigenstates, projective measurements, and rigorous statistical analysis of measurement outcomes to detect threats.

To protect against Photon Number Splitting (PNS) attacks inherent in real-world telecommunications, the framework integrates the **Decoy-State Method**, utilizing simulated Optical Quantum Random Number Generator (OQRNG) seeds to mix signal and decoy states.

## 🧠 The Threat Detection Matrix (Zero AI)
Our framework identifies the four mandated cyber threats using pure quantum statistical physics evaluated via our custom **Attack Simulation Harness**:

1. **Eavesdropping (Quantum Channel Manipulation):** Detected via *State Fidelity Degradation*. An intercept-resend attack forces wave-function collapse. The framework calculates the state fidelity (F) of the recovered signature. If F ≤ 66.7%, the channel is flagged as compromised.
2. **Forgery:** Detected via *Asymmetric Mismatch Thresholds*. The framework replaces legacy symmetrization with a mathematical gap evaluated via exact binomial bounds and Chernoff-Hoeffding limits (optimized to a key length of 4096 to prevent threshold overlap). We enforce s_a < s_v < 0.5. Any forged signature mathematically exceeds this threshold gap.
3. **Replay Attacks:** Detected via *No-Cloning State Collapse*. Teleportation strictly consumes the pre-shared Bell state. If classical transmission bits are replayed, Pauli corrections apply to vacuum noise, causing state fidelity to crash to exactly 50%.
4. **Photon Number Splitting (PNS):** Detected via *Decoy-State Verification*. Evaluates the single-photon yield lower bound (Y_1^L). If Y_1^L ≤ 0 or the decoy count falls outside the expected exact binomial interval, the protocol aborts.

## 🏗️️ Tech Stack
* **Quantum Simulation Engine:** Python 3.10+, IBM Qiskit (using `qiskit-aer` for realistic depolarizing noise models)
* **Statistical Physics Engine:** NumPy, SciPy
* **Enterprise API Layer:** FastAPI (RESTful ETSI GS QKD 014 compliance)
* **Frontend Dashboard:** React.js (Vite), Tailwind CSS, Recharts
* **Deployment:** Docker & Docker Compose

## 📁 Repository Structure
```text
SIH-DTPT-Framework/
├── frontend/                  # React UI for signature execution & visualization
│   └── Dockerfile             # Frontend container config
├── backend/                   
│   ├── api/                   # FastAPI ETSI GS QKD 014 REST endpoints
│   ├── quantum_engine/        # Qiskit teleportation & decoy states
│   ├── watchdog/              # Mathematical threat detection & simulation harness
│   ├── Dockerfile             # Backend container config
│   └── main.py                # FastAPI entry point
├── docs/                      
│   ├── TRD.md                 # Technical Requirements Document
│   └── forgery_attack_demo.png # Dashboard screenshot
├── memory-bank/               # AI context and progress tracking
├── docker-compose.yml         # One-click deployment config
└── README.md
```

## Measurement Distribution Visualization
Our primary demonstration features the Measurement Distribution Visualizer.

When running the attack_simulation_harness.py, the frontend visualizes the Pauli measurement outcome distribution. Under normal operation, the mismatch rate remains safely below the s_a limit. When the judge clicks "Execute Forgery Attack," the UI explicitly visualizes the measurement distribution curve shifting violently to the right, crossing the s_v limit and triggering an immediate, mathematically proven protocol abort.

## ⚙️ How to Run the Prototype

**Option 1: Docker (Recommended)**
You can run the entire full-stack application (frontend and backend) with a single command. Ensure Docker Desktop is running on your machine:

```Bash
docker-compose up --build
```

* The API will be available at http://localhost:8000
* The Interactive Dashboard will be available at http://localhost:5173

**Option 2: Manual Setup**
If you prefer to run the services manually without Docker:

1. Start the Quantum Backend:

```Bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --reload
```

2. Start the Visualization Frontend:

```Bash
cd frontend
npm ci
npm run dev
```
