# Decision Log and Known Risks — DTPT Framework

This file records the architectural decisions behind the prototype, including corrections to earlier claims. Each entry states what was decided, why, and what it costs.

| ADR | Decision | Status |
|---|---|---|
| 001 | No AI/ML in threat detection | Active |
| 002 | Teleportation with outsourced BSM (corrects an earlier "MDI / twin-field" label) | Active (corrected) |
| 003 | Decoy-state method as a photon-level NumPy model | Active |
| 004 | ETSI GS QKD 014-style REST API, with two documented deviations | Active |
| 005 | Simulated OQRNG: Poisson source, unbiased extractor, seeded bulk generator | Active |
| 006 | Cached deferred-measurement density matrices | Active |
| 007 | Single-qubit tokens; BCGST encoding not implemented | Active (accepted limitation) |
| 008 | Batch-mean fidelity, replay checked first | Active |
| 009 | Inclusive replay band (floating-point fix) | Active |
| 010 | Mock mTLS via forwarded-fingerprint header | Active (demo only) |
| 011 | Key length L = 4096 | Active (supersedes the earlier 1,024 cap) |
| 012 | Package layout to avoid the `watchdog` name collision | Active |
| 013 | Threshold calibration: thirds split, cloning floor, exact tails | Active |
| 014 | PNS detection rules | Active |
| 015 | Frontend toolchain: Vite, Tailwind 3.4, Recharts 3, pinned versions | Active |

---

## ADR-001: No AI/ML in threat detection

- **Decision.** Threat detection uses only fixed comparisons against physical and statistical bounds. No machine-learning library is imported anywhere in the codebase.
- **Rationale.** The problem statement asks for detection without AI/ML. Fixed bounds are also auditable: every verdict can be traced to one inequality and recomputed by hand.
- **Cost.** The bounds are only as good as the threat model behind them. An attack outside that model (for example, a detector side channel) is not covered. That is a property of any fixed-bound design, and THREAT_MODEL.md lists what is out of scope.

## ADR-002: Teleportation with outsourced Bell-state measurement (corrected)

- **Decision.** Alice holds the token and one half of a Bell pair shared with Bob. Charlie, an untrusted relay, performs the Bell-state measurement on Alice's two qubits and broadcasts 2 bits. Bob applies the Pauli correction.
- **Correction.** Earlier project documents described this as a measurement-device-independent (MDI) or twin-field topology. That label was wrong. In MDI schemes the relay measures signals arriving from *both* parties, which removes detector side channels at the endpoints. Our relay measures two qubits that both originate with Alice. We also removed an unverified claim of alignment with a specific national network standard.
- **Cost.** The design does not inherit MDI's immunity to detector attacks. Moving to a genuine MDI-QDS layout is future work.

## ADR-003: Decoy-state method as a photon-level NumPy model

- **Decision.** Alice randomly sends signal (μ = 0.5), weak decoy (ν = 0.1) and vacuum pulses with probabilities 0.7, 0.2 and 0.1. Photon numbers are Poisson-distributed, losses are binomial, and dark counts and misalignment are included. Bob isolates the decoy pulses and computes per-class gain and QBER, plus the Ma-Qi-Zhao-Lo single-photon yield lower bound Y₁ᴸ.
- **Rationale.** Qiskit simulates qubits, not multi-photon optical pulses. PNS attacks only exist at the photon-number level, so that layer is modelled with exact photon statistics in NumPy.
- **Cost.** The decoy channel and the qubit teleportation run as two parallel models of the same fiber, not one unified simulation (roadmap R6).

## ADR-004: ETSI GS QKD 014-style REST API

- **Decision.** The API exposes `status`, `enc_keys` and `dec_keys` with ETSI-shaped request and response bodies, and returns HTTP 403 with `{"error": "ABORT_…"}` on any Watchdog abort.
- **Deviations from the standard.**
  1. `enc_keys` returns a `key_ID` with status `PENDING` and withholds the key. Only `dec_keys` releases it, after the Watchdog passes.
  2. DTPT telemetry travels in the standard's extension fields.
- **Rationale.** Using a recognised key-delivery interface shows how the framework would plug into existing infrastructure, and avoids inventing a proprietary API.

## ADR-005: Simulated OQRNG

- **Decision.** Raw entropy comes from Poisson-distributed photon counts (`numpy.random.Generator.poisson`, λ = 10).
  - Raw counts taken mod 6 would be biased. Bits are therefore extracted by comparing pairs of independent counts (a < b → 0, a > b → 1, ties discarded). This is exactly unbiased for i.i.d. samples.
  - Uniform choices among the six Pauli eigenstates then use exact rejection sampling on those bits.
  - Bulk decoy modulation (10⁶ pulses) uses a PCG64 generator seeded with 256 OQRNG bits. Drawing every pulse through the extractor took 5.9 s per session; the seeded generator takes 0.14 s.
- **Honest scope.** This is a *simulation* of an optical QRNG. NumPy's generator is pseudo-random, so the entropy is not physical. Pauli basis selection always uses the extractor directly; only decoy-class assignment uses the seeded generator.

## ADR-006: Cached deferred-measurement density matrices

- **Decision.** Bob's received state depends only on the token, the attack branch and the noise parameters. Those 28 circuits (6 honest, 18 intercept-resend, 4 replay) run once in Qiskit Aer's density-matrix mode and are cached. Per-token measurement outcomes are then sampled with the Born rule.
  - Charlie's mid-circuit measurement is replaced by quantum-controlled corrections (the principle of deferred measurement). This gives Bob exactly the same reduced state, without sampling noise.
  - The mid-circuit (`if_test`) version is kept in `teleportation.py` for reference and testing.
- **Rationale.** Running one circuit per token would be far too slow for a live demo. With caching, a full session takes about 0.11 s.
- **Cost.** The Watchdog currently reads the fidelity from the simulated density matrix, which a real receiver cannot observe (roadmap R2).

## ADR-007: Single-qubit tokens; BCGST encoding not implemented

- **Decision.** Tokens are teleported as single qubits.
- **Rationale.** The Barnum-Crépeau-Gottesman-Smith-Tapp (BCGST) result implies that authenticating quantum states requires encoding them. A multi-qubit error-detecting code would multiply simulation cost and was deferred.
- **Cost.** The prototype does not satisfy that requirement. This is a stated limitation, not a solved problem.

## ADR-008: Batch-mean fidelity, replay checked first

- **Decision.** Fidelity rules are applied to the mean fidelity over all L tokens. Replay (\|F̄ − 0.5\| ≤ 0.01) is checked before intercept-resend (F̄ ≤ 0.6667).
- **Rationale.**
  - The 2/3 limit is an average. An intercepted token where Eve chose the wrong basis has F = 0.5 on its own, so a per-token check would mislabel intercept-resend as replay.
  - F = 0.5 also satisfies F ≤ 0.6667, so the order of the checks is what separates the two attacks.
- **Earlier version.** The original documents specified `F == 0.5` as an exact equality. That is replaced by a tolerance band, because channel noise makes exact equality unreachable.

## ADR-009: Inclusive replay band (bug found by tests)

- **Decision.** The replay check is `abs(F − 0.5) <= 0.01 + 1e-9`.
- **Rationale.** The first implementation used `np.isclose(F, 0.5, atol=0.01)`, which rejects F = 0.51 because 0.51 − 0.5 = 0.0100000000000000089 in floating point. `tests/test_fidelity.py` caught it. The 1e-9 slack only absorbs floating-point rounding.

## ADR-010: Mock mTLS via forwarded-fingerprint header

- **Decision.** ETSI routes read `X-SSL-Client-Cert-SHA256` and look the value up in an in-code node registry.
  - An unknown or missing fingerprint gets 401.
  - A known node calling an endpoint its role does not allow gets 403.
  - The frontend attaches Alice's fingerprint for `enc_keys` and `status`, and Bob's for `dec_keys`, using an Axios interceptor.
- **Honest scope.** This simulates what a TLS-terminating proxy would forward after verifying a real client certificate. The demo fingerprints are compiled into the public frontend bundle, so anyone can reuse them. It is not mTLS and gives no real authentication.

## ADR-011: Key length L = 4096

- **Decision.** The default number of tokens per signature is 4096. This supersedes the earlier plan to cap L at 1,024 for latency.
- **Rationale.** A 400-session sweep at L = 1024 labelled 7.5% of intercept-resend runs as `ABORT_FORGERY`. They were still aborted, but under the wrong label, because random variation in Eve's basis choices left batch fidelity just above 0.6667.
  - At L = 4096 the mislabel rate fell to 1 in 400.
  - The exact bound on accepting a forgery fell from about 2 × 10⁻⁵ to about 1.5 × 10⁻¹⁶.
  - Latency was unchanged at 0.11 s, thanks to ADR-006.

## ADR-012: Package layout to avoid the `watchdog` name collision

- **Decision.** `quantum_engine/`, `watchdog/` and `api/` are regular packages (they contain `__init__.py`), and `pytest.ini` sets `pythonpath = .`.
- **Rationale.** A popular PyPI package is also called `watchdog`, and it is often installed alongside uvicorn's reload tooling. Without these two measures, `import watchdog` silently resolves to that package instead of ours.

## ADR-013: Threshold calibration

- **Decision.** Thresholds are derived from two error rates:
  - **Honest error rate:** e_h = 1 − min F over the six tokens. For a pure token, the probability of a mismatch is exactly 1 − F.
  - **Forger floor:** e_f = 1/6, from the 5/6 fidelity limit of an optimal universal 1→2 qubit cloner.
  - **Thresholds:** split the gap in thirds, so s_a = e_h + (e_f − e_h)/3 and s_v = e_h + 2(e_f − e_h)/3.
  - The code enforces 0 ≤ e_h < s_a < s_v < e_f ≤ 0.5.
  - Decisions compare integer counts (mismatches ≥ ⌈s_a·L⌉), not floats.
- **Bounds reported.** Hoeffding bounds, which hold for any distribution, and exact binomial tails under the i.i.d. per-token model. The exact tails are much tighter at our key lengths.
- **Cost.** Only a blind forger (mismatch ≈ 0.5) is simulated so far. The cloning forger that the thresholds are designed against is roadmap R3.

## ADR-014: PNS detection rules

- **Decision.** The session aborts with `ABORT_EAVESDROP` (variant `PNS`) if either rule fires:
  1. The single-photon yield lower bound satisfies Y₁ᴸ ≤ 0.
  2. The number of decoy detections falls outside its exact binomial acceptance interval, set so an honest channel triggers it with probability at most 10⁻⁶.
- **Rationale.** A PNS attacker tuned to match the signal gain cannot also match the decoy gain. In simulation, decoy detections drop about 4× and Y₁ᴸ goes negative, while token fidelity is untouched.

## ADR-015: Frontend toolchain

- **Decision.** Vite 6, React 18.3.1, Tailwind CSS 3.4.19, Recharts 3.10.1 (which needs `react-is` 18.3.1) and Axios 1.20.0. All versions are pinned exactly, with `package-lock.json` committed. Tests use Vitest with Testing Library.
- **Rationale.**
  - Create React App was deprecated in 2025.
  - Tailwind 4 drops `tailwind.config.js`.
  - Recharts 2 is end-of-life.
  - `@testing-library/jest-dom` 6.10.0 is a deprecated, broken release, so 6.9.1 is pinned instead.

---

## Known risks

| Risk | Impact | Mitigation |
|---|---|---|
| Noise parameters changed without recalibration | False forgery aborts on an honest channel | Thresholds are derived from the configured noise at startup (ADR-013), so they stay consistent automatically. Raising noise until e_h ≥ e_f raises `ThresholdConfigurationError` instead of failing silently. |
| Render free-tier cold start or restart | First request is slow; in-memory sessions are lost | UptimeRobot ping every 5 min; 60 s client timeout; record a backup demo video; keep a local run ready. |
| Library API changes (Qiskit and others) | Backend breaks on upgrade | Pin backend versions in `requirements.txt` to the tested set (see testing.md §5). Do not upgrade right before a demo. |
| Over-interpreting the simulation | Claims that exceed what is modelled | Limitations are listed in architecture.md §9 and THREAT_MODEL.md §5. |
