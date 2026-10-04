# Testing — DTPT Framework

**Current results:** 115 backend tests and 10 frontend tests, all passing. A 2,000-session validation campaign has also been run (§4).

Tests check the mathematical boundaries directly: each Watchdog rule is exercised at, just below and just above its threshold, and checked end to end through the Qiskit engine. No AI/ML testing tools are used.

---

## 1. Running the tests

```bash
# Backend: run from backend/ (pytest.ini sets pythonpath and testpaths)
pip install -r requirements.txt pytest httpx
pytest -v

# Frontend
cd frontend
npm ci
npm test            # vitest run
```

`backend/pytest.ini` puts `backend/` first on `sys.path`. Without it, the PyPI package `watchdog` can shadow our `watchdog/` package (decision_log ADR-012).

## 2. Backend suites (implemented)

### 2.1 `tests/test_fidelity.py` — replay and intercept-resend (62 cases)

| Area | What is proven |
|---|---|
| Intercept-resend | F = 0.65 aborts. Every F ≤ 0.6667 outside the replay band aborts, including exactly 2/3. The limit is inclusive: the next float above 0.6667 passes. |
| Replay | F = 0.5 aborts. The whole band [0.49, 0.51] is replay, endpoints included (the regression test for ADR-009). |
| Rule order | 0.5 is labelled replay, not eavesdropping. Values just outside the band fall through to eavesdropping. |
| Qiskit physics | A replayed correction on I/2 gives F = 0.5 for all 24 combinations of token and broadcast. Noiseless intercept-resend averages exactly 2/3 for every token. |
| Batch evaluation | A batch of intercepted tokens is labelled eavesdropping even though individual tokens show 0.5. A batch of replayed tokens is labelled replay. |
| Input validation | NaN, ±inf, values below 0 or above 1, and empty batches are rejected. Float rounding just above 1 is clamped. |

### 2.2 `tests/test_thresholds.py` — forgery (53 cases)

| Area | What is proven |
|---|---|
| Forgery rule | With s_a = 0.05, s_v = 0.08 and m = 0.07, the session aborts with the `VERIFIED_ONLY` tier. Every count ≥ ⌈s_a·L⌉ aborts. |
| Exact boundaries | 0.05 × 100 gives a count limit of 5, not 6. The verdict never drops back to a lower tier as the mismatch count rises, checked across all 4,097 possible counts. |
| Configuration | Every violation of 0 ≤ e_h < s_a < s_v < e_f ≤ 0.5 is rejected, as are NaN thresholds and L = 0. A channel noisier than the forger floor is refused. |
| Bounds | The exact binomial tail never exceeds the Hoeffding bound. Bounds shrink as L grows. `minimum_key_length(ε)` satisfies all three bounds for ε = 10⁻³, 10⁻⁶ and 10⁻⁹. |
| Visualizer data | Each distribution curve sums to 1 and has the expected mean. |
| End to end (Qiskit) | 10 honest sessions are all authenticated. 10 blind forgeries all exceed s_v and are rejected. A forgery leaves the channel fidelity unchanged, so it is labelled as forgery rather than eavesdropping. |

## 3. Frontend suites (implemented)

| File | Tests | What is proven |
|---|---|---|
| `src/api.test.js` | 5 | The interceptor sends Alice's fingerprint to `enc_keys` and `status`, Bob's to `dec_keys`, and no header to `/simulate` or `/health`. A 403 from `dec_keys` resolves instead of throwing. Per-call overrides work. |
| `src/components/Visualizer.test.jsx` | 3 | Both threshold `ReferenceLine`s and both curves render as SVG. A forged curve has more than 99% of its probability mass beyond s_v. A placeholder shows when there is no data. |
| `src/components/Dashboard.test.jsx` | 2 | "Sign Document" renders. Clicking "Execute Forgery" sends `FORGERY` and displays `HTTP 403 Forbidden · ABORT_FORGERY`. |

## 4. Validation campaign (statistical)

Settings: L = 4096, depolarizing p = 0.02, 100 km fiber, 10⁶ decoy pulses, 400 sessions per scenario.

| Scenario | Correct verdict |
|---|---|
| Honest | 400 / 400 `VERIFIED` (0 false aborts) |
| Forgery | 400 / 400 `ABORT_FORGERY` |
| Replay | 400 / 400 `ABORT_REPLAY` |
| Intercept-resend | 399 / 400 `ABORT_EAVESDROP` (1 aborted as `ABORT_FORGERY`) |
| PNS | 400 / 400 `ABORT_EAVESDROP` (`PNS`) |

How to read these numbers:

- **Statistical strength.** Zero failures in 400 runs puts a 95% upper bound of about 0.75% on that failure rate (the "rule of three"). Stronger guarantees come from the analytic bounds, not from run counts. For example, the exact probability of accepting a cloning-level forger is about 1.5 × 10⁻¹⁶ at L = 4096.
- **What Qiskit actually runs.** Qiskit Aer computes the 28 distinct density matrices once (ADR-006). Each session then samples measurement outcomes from those states.
- **Reproducibility.** This campaign was run ad hoc. A reproducible script is still to be written (§6).
- **Earlier run that informed ADR-011.** A sweep at L = 1024 mislabelled 30 of 400 intercept-resend sessions.

## 5. Tested versions

Backend:

| Package | Version |
|---|---|
| Python | 3.12.3 |
| numpy | 2.4.4 |
| scipy | 1.17.1 |
| qiskit | 2.5.2 |
| qiskit-aer | 0.17.2 |
| fastapi | 0.141.1 |
| pydantic | 2.13.5 |
| uvicorn | 0.54.0 |
| httpx | 0.28.1 |
| pytest | 9.1.1 |

Frontend: exact pins in `frontend/package.json`, plus `package-lock.json`.

## 6. Not yet implemented

| Planned file | Purpose |
|---|---|
| `tests/test_health_check.py` | `GET /health` returns `{"status": "online"}` |
| `tests/test_oqrng.py` | Raw stream has variance/mean ≈ 1 (Poisson). Extracted bits and token choices are uniform. |
| `tests/test_teleportation.py` | Bell-pair fidelity is 1. All 6 tokens × 4 broadcasts teleport with fidelity 1. The mid-circuit version produces 0 mismatches without noise. |
| `tests/test_decoy_stats.py` | An honest channel passes. PNS raises `PNSAttackException`, through both the Y₁ᴸ rule and the interval rule. |
| `tests/test_etsi_routes.py` | Full flow `enc_keys` → `dec_keys` returns 200 with a key. An aborted session returns 403 `{"error": …}` with no key. A wrong master or unknown `key_ID` returns 404. |
| `tests/test_security.py` | Missing or unknown fingerprint → 401. Wrong role → 403. |
| `validation/run_campaign.py` | Reproducible version of §4, writing a CSV and a summary table. |

Each roadmap item (R1–R4 in architecture.md §9) also needs its own tests when it is implemented.
