# Dual-Threshold Projective Teleportation (DTPT) Framework

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![Qiskit](https://img.shields.io/badge/Qiskit-Supported-purple)
![FastAPI](https://img.shields.io/badge/FastAPI-Ready-009688)
![License](https://img.shields.io/badge/License-MIT-green)

> **Official Smart India Hackathon (SIH) Solution**
> 
> For full mathematical proofs, threat models, and extended architecture details, please refer to the official document: **Quantum Digital Signature SIH Solution.pdf**.

## 📖 Executive Summary

As the world transitions to quantum-safe communications, relying on classical encryption or computationally heavy mathematical algorithms is only a temporary fix. True, long-term security requires **Information-Theoretic Security**—protection guaranteed by the laws of physics.

The **Dual-Threshold Projective Teleportation (DTPT) Framework** is a highly practical, software-defined architecture for Quantum Digital Signatures. Designed explicitly without Artificial Intelligence or Machine Learning, this framework relies entirely on **Pauli eigenstates, projective measurements, strict statistical thresholds, and the Decoy-State Method**. It successfully bridges theoretical quantum physics with the hardware realities of modern telecommunications.

## ✨ Core Features

### 1. Practical Quantum Routing (MDI Topology)
Bypasses traditional key-sharing vulnerabilities using a **Measurement-Device-Independent (MDI)** or "Twin-Field" routing topology.
- Neil and Nitin communicate via an untrusted central router (Mukesh).
- Mukesh performs Bell-State Measurements (BSM). Even if compromised, Mukesh only observes high-dimensional quantum noise.
- Aligns with India's indigenous C-DOT Q-AKSHAY network specifications.

### 2. OQRNG & BCGST Error Subspaces
- **OQRNG:** Mathematically simulates an Optical Quantum Random Number Generator using the natural Poisson distribution of photon-arrival times.
- **BCGST Theorem:** Encodes signatures into a 3-qubit logical error-detecting subspace. Any interception forces an irreversible error matrix, physically preventing forgery.

### 3. The Decoy-State Method (Deceptive Defense)
Defends against sophisticated Photon Number Splitting (PNS) attacks:
- **Channel Flooding:** Mixes actual signal states with randomly inserted "decoy states" (varying mean photon intensities).
- **Statistical Trap:** Eavesdroppers (Eve) inevitably interact with decoys, altering photon number statistics.
- **Verification:** The Bit Error Rate (BER) of decoy pulses instantly exposes eavesdroppers, aborting the protocol.

### 4. Zero-AI Threat Detection Matrix
Detects all mandated cyber threats using pure, deterministic statistical physics:
- **Eavesdropping:** Detected via Fidelity Degradation. Drops below 66.7% (2/3) fidelity trigger a compromise alert.
- **Forgery:** Utilizes Asymmetric Mismatch Thresholds ($s_a < s_v < 0.5$) to mathematically reject forged signatures.
- **Replay Attacks:** Teleportation consumes the Bell state. Replaying classical bits yields 50% fidelity (pure noise), flagging an immediate alert.

## 🛠 Implementation Stack

- **Core Engine:** `IBM Qiskit` (Python) for circuit simulation, Bell-state generation, and Pauli correction routing.
- **Statistical Watchdog:** `NumPy` & `SciPy` for Decoy-State BER analysis, density matrix algebra, and calculating threshold bounds.
- **API Layer:** `FastAPI` to simulate enterprise node requests and serve authenticated JSON payloads, making it enterprise-ready for Web3 and decentralized economies (compliant with ETSI GS QKD 014).

## 🚀 Installation & Setup

Ensure you have Python 3.8+ installed. The following instructions will set up the environment on your Mac or Linux terminal:

```bash
# 1. Clone the repository
git clone https://github.com/your-username/dtpt-quantum-signatures.git
cd dtpt-quantum-signatures

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install required dependencies
pip install qiskit numpy scipy fastapi uvicorn
```

## 💻 Usage (Local Simulation)

To spin up the Fast API server simulating the enterprise nodes:

```bash
uvicorn main:app --reload
```
Once running, you can interact with the quantum routing APIs via `http://localhost:8000/docs`.

## 👨‍💻 Author / Maintainer

**CypherX**

