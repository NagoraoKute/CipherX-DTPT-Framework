/**
 * Dashboard.jsx — DTPT Framework main console (dark mode, Tailwind only).
 *
 * Signature Console   "Sign Document": ETSI enc_keys (Alice) -> status -> dec_keys (Bob).
 * Attacker Panel      Runs the Attack Simulation Harness, then asks the ETSI
 *                     dec_keys gate for the same key_ID to prove it answers 403.
 * Watchdog Rules      The four deterministic checks, in evaluation order.
 * Visualizer          Mismatch distribution vs. s_a / s_v.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ATTACK_TYPES,
  checkHealth,
  describeApiError,
  getChannelStatus,
  requestSignature,
  retrieveVerifiedKey,
  simulateAttack,
} from "../api.js";
import Visualizer from "./Visualizer.jsx";

const CLASSICAL_LIMIT = 0.6667;
const REPLAY_BAND = [0.49, 0.51];

const ATTACK_BUTTONS = [
  {
    type: ATTACK_TYPES.NONE,
    label: "Run Honest Baseline",
    description: "Untouched channel: all four rules should pass.",
    tone: "emerald",
  },
  {
    type: ATTACK_TYPES.FORGERY,
    label: "Execute Forgery",
    description: "Forger claims token labels without the private key.",
    tone: "rose",
  },
  {
    type: ATTACK_TYPES.REPLAY,
    label: "Execute Replay Attack",
    description: "Old BSM broadcast replayed onto an unentangled qubit.",
    tone: "rose",
  },
  {
    type: ATTACK_TYPES.INTERCEPT_RESEND,
    label: "Execute Eavesdropping",
    description: "Intercept-resend: Eve measures and re-prepares each token.",
    tone: "rose",
  },
  {
    type: ATTACK_TYPES.PNS,
    label: "Execute PNS Attack",
    description: "Photon number splitting on multi-photon pulses.",
    tone: "rose",
  },
];

const STATUS_STYLES = {
  IDLE: "border-slate-600 bg-slate-800/60 text-slate-300",
  AUTHENTICATING: "border-sky-500/60 bg-sky-500/10 text-sky-300",
  VERIFIED: "border-emerald-500/60 bg-emerald-500/10 text-emerald-300",
  ABORTED: "border-rose-500/70 bg-rose-500/10 text-rose-300 animate-pulse-ring",
  ERROR: "border-amber-500/60 bg-amber-500/10 text-amber-300",
};

const BUTTON_TONES = {
  emerald: "border-emerald-500/40 hover:border-emerald-400 hover:bg-emerald-500/10 focus-visible:ring-emerald-400",
  rose: "border-rose-500/40 hover:border-rose-400 hover:bg-rose-500/10 focus-visible:ring-rose-400",
};

const pct = (value, digits = 2) => (Number.isFinite(value) ? `${(value * 100).toFixed(digits)}%` : "—");
const fixed = (value, digits = 4) => (Number.isFinite(value) ? value.toFixed(digits) : "—");
const sci = (value) => (Number.isFinite(value) ? value.toExponential(2) : "—");

function statusFromVerdict(verdict) {
  if (!verdict) return "IDLE";
  return verdict === "VERIFIED" ? "VERIFIED" : "ABORTED";
}

/** The four Watchdog rules in the exact order the backend applies them. */
function buildRuleRows(simulation) {
  if (!simulation) return [];
  const { telemetry, watchdog } = simulation;
  const fidelity = telemetry.state_fidelity;
  const decoy = watchdog.decoy;
  const mismatch = watchdog.mismatch;
  const isReplay = fidelity >= REPLAY_BAND[0] && fidelity <= REPLAY_BAND[1];

  return [
    {
      id: "replay",
      name: "Replay (no-cloning collapse)",
      rule: "F ∈ [0.49, 0.51] → ABORT_REPLAY",
      measured: `F = ${fixed(fidelity)}`,
      tripped: isReplay,
    },
    {
      id: "eavesdrop",
      name: "Intercept-resend (2/3 limit)",
      rule: "F ≤ 0.6667 → ABORT_EAVESDROP",
      measured: `F = ${fixed(fidelity)}`,
      tripped: !isReplay && fidelity <= CLASSICAL_LIMIT,
    },
    {
      id: "pns",
      name: "Photon number splitting (decoy)",
      rule: "Y₁ᴸ ≤ 0 or decoy count ∉ interval → ABORT_EAVESDROP",
      measured: `Y₁ᴸ = ${sci(decoy.single_photon_yield_lower_bound)} · decoy ${decoy.decoy_detections} vs [${decoy.acceptance_interval.join(", ")}]`,
      tripped: decoy.violations.length > 0,
    },
    {
      id: "forgery",
      name: "Forgery (dual threshold)",
      rule: `mismatch ≥ s_a (${pct(mismatch.s_a)}) → ABORT_FORGERY`,
      measured: `m = ${pct(mismatch.mismatch_rate)} (${mismatch.verdict})`,
      tripped: mismatch.verdict !== "AUTHENTICATED",
    },
  ];
}

function StatusBadge({ status, label }) {
  return (
    <span
      data-testid="status-badge"
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-xs font-semibold tracking-wider ${STATUS_STYLES[status]}`}
    >
      <span className="h-2 w-2 rounded-full bg-current" />
      {label ?? status}
    </span>
  );
}

function Card({ title, subtitle, children, className = "" }) {
  return (
    <section className={`rounded-xl border border-quantum-700 bg-quantum-900/80 p-5 shadow-lg shadow-black/30 ${className}`}>
      <header className="mb-4">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-slate-300">{title}</h2>
        {subtitle && <p className="mt-1 text-xs text-slate-500">{subtitle}</p>}
      </header>
      {children}
    </section>
  );
}

function Metric({ label, value, hint, danger = false }) {
  return (
    <div className="rounded-lg border border-quantum-700 bg-quantum-950/60 p-3">
      <div className="text-[11px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 font-mono text-lg ${danger ? "text-rose-400" : "text-slate-100"}`}>{value}</div>
      {hint && <div className="mt-0.5 font-mono text-[11px] text-slate-500">{hint}</div>}
    </div>
  );
}

export default function Dashboard() {
  const [backendOnline, setBackendOnline] = useState(null);
  const [signature, setSignature] = useState({ status: "IDLE" });
  const [simulation, setSimulation] = useState(null);
  const [etsiGate, setEtsiGate] = useState(null);
  const [busyAction, setBusyAction] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);

  const runSimulation = useCallback(async (attackType) => {
    setBusyAction(attackType);
    setErrorMessage(null);
    try {
      const result = await simulateAttack(attackType);
      setSimulation(result);
      setEtsiGate(await retrieveVerifiedKey(result.transaction_id));
    } catch (error) {
      setErrorMessage(describeApiError(error));
    } finally {
      setBusyAction(null);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    checkHealth()
      .then(() => {
        if (cancelled) return;
        setBackendOnline(true);
        runSimulation(ATTACK_TYPES.NONE);
      })
      .catch(() => !cancelled && setBackendOnline(false));
    return () => {
      cancelled = true;
    };
  }, [runSimulation]);

  const signDocument = useCallback(async () => {
    setBusyAction("SIGN");
    setErrorMessage(null);
    setSignature({ status: "AUTHENTICATING" });
    try {
      const { keyId } = await requestSignature();
      const channel = await getChannelStatus();
      const gate = await retrieveVerifiedKey(keyId);
      setSignature({
        status: gate.ok ? "VERIFIED" : "ABORTED",
        keyId,
        channelValid: channel.status_extension?.isValid,
        httpStatus: gate.httpStatus,
        details: gate.ok ? gate.data.key_container_extension : gate.data,
        keyPreview: gate.ok ? gate.data.keys[0].key : null,
      });
    } catch (error) {
      setSignature({ status: "ERROR" });
      setErrorMessage(describeApiError(error));
    } finally {
      setBusyAction(null);
    }
  }, []);

  const ruleRows = useMemo(() => buildRuleRows(simulation), [simulation]);
  const verdict = simulation?.watchdog.status;
  const variant = simulation?.watchdog.variant;
  const attackActive = Boolean(verdict && verdict !== "VERIFIED");
  const firstTripped = ruleRows.find((row) => row.tripped)?.id;
  const thresholds = simulation?.telemetry.thresholds;
  const decoy = simulation?.watchdog.decoy;

  return (
    <div className="min-h-screen bg-quantum-950 font-sans text-slate-200">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {/* Header */}
        <header className="mb-8 flex flex-col gap-4 border-b border-quantum-700 pb-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.3em] text-cyan-400">Cypher#X</p>
            <h1 className="mt-2 text-2xl font-bold text-white sm:text-3xl">Dual-Threshold Projective Teleportation</h1>
            <p className="mt-1 text-sm text-slate-400">
              Deterministic quantum-signature threat detection. Zero AI/ML. Every verdict is a fixed physical bound.
            </p>
          </div>
          <div className="flex items-center gap-2 font-mono text-xs" data-testid="backend-health">
            <span
              className={`h-2.5 w-2.5 rounded-full ${
                backendOnline === null ? "bg-slate-500" : backendOnline ? "bg-emerald-400" : "bg-rose-500"
              }`}
            />
            <span className="text-slate-400">
              {backendOnline === null ? "Connecting…" : backendOnline ? "Quantum backend online" : "Backend offline"}
            </span>
          </div>
        </header>

        {errorMessage && (
          <div role="alert" className="mb-6 rounded-lg border border-amber-500/50 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
            {errorMessage}
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-3">
          {/* Left column */}
          <div className="flex flex-col gap-6">
            <Card title="Signature Console" subtitle="ETSI GS QKD 014 · Alice → Charlie (BSM) → Bob">
              <div className="flex items-center justify-between">
                <StatusBadge status={signature.status} />
                <button
                  type="button"
                  onClick={signDocument}
                  disabled={busyAction !== null}
                  className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-quantum-950 transition hover:bg-cyan-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {busyAction === "SIGN" ? "Teleporting…" : "Sign Document"}
                </button>
              </div>

              {signature.keyId && (
                <dl className="mt-4 space-y-2 font-mono text-xs">
                  <div className="flex justify-between gap-4">
                    <dt className="text-slate-500">key_ID</dt>
                    <dd className="truncate text-slate-300">{signature.keyId}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-slate-500">dec_keys</dt>
                    <dd className={signature.httpStatus === 200 ? "text-emerald-400" : "text-rose-400"}>
                      HTTP {signature.httpStatus} {signature.httpStatus === 200 ? "OK" : "Forbidden"}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-slate-500">decoy channel</dt>
                    <dd className={signature.channelValid ? "text-emerald-400" : "text-rose-400"}>
                      {signature.channelValid ? "isValid" : "compromised"}
                    </dd>
                  </div>
                  {signature.status === "VERIFIED" && (
                    <>
                      <div className="flex justify-between gap-4">
                        <dt className="text-slate-500">fidelity F</dt>
                        <dd>{fixed(signature.details.state_fidelity)}</dd>
                      </div>
                      <div className="flex justify-between gap-4">
                        <dt className="text-slate-500">mismatch</dt>
                        <dd>
                          {pct(signature.details.mismatch_rate)} &lt; s_a {pct(signature.details.s_a)}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-4">
                        <dt className="text-slate-500">key</dt>
                        <dd className="truncate text-cyan-300">{signature.keyPreview.slice(0, 24)}…</dd>
                      </div>
                    </>
                  )}
                  {signature.status === "ABORTED" && (
                    <div className="flex justify-between gap-4">
                      <dt className="text-slate-500">abort</dt>
                      <dd className="text-rose-400">{signature.details.error}</dd>
                    </div>
                  )}
                </dl>
              )}
            </Card>

            <Card title="Attacker Control Panel" subtitle="Attack Simulation Harness · demo only">
              <div className="grid gap-2">
                {ATTACK_BUTTONS.map(({ type, label, description, tone }) => (
                  <button
                    key={type}
                    type="button"
                    onClick={() => runSimulation(type)}
                    disabled={busyAction !== null}
                    className={`rounded-lg border bg-quantum-950/60 px-4 py-3 text-left transition focus:outline-none focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-50 ${BUTTON_TONES[tone]}`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-semibold text-slate-100">{label}</span>
                      {busyAction === type && <span className="font-mono text-[11px] text-slate-400">running…</span>}
                    </div>
                    <p className="mt-0.5 text-xs text-slate-500">{description}</p>
                  </button>
                ))}
              </div>
            </Card>
          </div>

          {/* Right columns */}
          <div className="flex flex-col gap-6 lg:col-span-2">
            <Card
              title="Watchdog Verdict"
              subtitle={simulation ? `Session ${simulation.transaction_id} · attack: ${simulation.attack_type}` : "No session yet"}
            >
              <div className="flex flex-wrap items-center gap-3">
                <StatusBadge
                  status={statusFromVerdict(verdict)}
                  label={verdict ? `${verdict}${variant ? ` · ${variant}` : ""}` : "IDLE"}
                />
                {etsiGate && (
                  <span
                    data-testid="etsi-gate"
                    className={`rounded-md border px-2.5 py-1 font-mono text-xs ${
                      etsiGate.ok
                        ? "border-emerald-500/40 text-emerald-300"
                        : "border-rose-500/50 bg-rose-500/5 text-rose-300"
                    }`}
                  >
                    GET dec_keys → HTTP {etsiGate.httpStatus} {etsiGate.ok ? "OK · key released" : `Forbidden · ${etsiGate.data.error}`}
                  </span>
                )}
              </div>

              {simulation && (
                <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
                  <Metric
                    label="Batch fidelity F"
                    value={fixed(simulation.telemetry.state_fidelity)}
                    hint="limit 0.6667 · replay 0.5"
                    danger={simulation.telemetry.state_fidelity <= CLASSICAL_LIMIT}
                  />
                  <Metric
                    label="Mismatch rate"
                    value={pct(simulation.telemetry.mismatch_rate)}
                    hint={`s_a ${pct(thresholds.s_a)} · s_v ${pct(thresholds.s_v)}`}
                    danger={simulation.telemetry.mismatch_rate >= thresholds.s_a}
                  />
                  <Metric
                    label="Decoy detections"
                    value={decoy.decoy_detections}
                    hint={`accept [${decoy.acceptance_interval.join(", ")}]`}
                    danger={decoy.violations.length > 0}
                  />
                  <Metric
                    label="Single-photon Y₁ᴸ"
                    value={sci(decoy.single_photon_yield_lower_bound)}
                    hint={`expected ${sci(decoy.expected_single_photon_yield)}`}
                    danger={decoy.single_photon_yield_lower_bound <= 0}
                  />
                </div>
              )}

              {ruleRows.length > 0 && (
                <ol className="mt-5 divide-y divide-quantum-700 rounded-lg border border-quantum-700" data-testid="watchdog-rules">
                  {ruleRows.map((row, index) => (
                    <li
                      key={row.id}
                      className={`flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between ${
                        row.id === firstTripped ? "bg-rose-500/10" : ""
                      }`}
                    >
                      <div>
                        <div className="text-sm text-slate-200">
                          <span className="mr-2 font-mono text-slate-500">{index + 1}.</span>
                          {row.name}
                          {row.id === firstTripped && (
                            <span className="ml-2 rounded bg-rose-500/20 px-1.5 py-0.5 font-mono text-[10px] text-rose-300">DECISIVE</span>
                          )}
                        </div>
                        <div className="font-mono text-[11px] text-slate-500">{row.rule}</div>
                      </div>
                      <div className="flex items-center gap-3 font-mono text-xs">
                        <span className="text-slate-400">{row.measured}</span>
                        <span className={row.tripped ? "text-rose-400" : "text-emerald-400"}>{row.tripped ? "TRIPPED" : "PASS"}</span>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </Card>

            <Card
              title="Measurement Distribution Visualizer"
              subtitle="Exact binomial distribution of Bob's projective mismatch rate · baseline vs. observed"
            >
              <Visualizer
                data={simulation?.telemetry.mismatch_distribution ?? []}
                sA={thresholds?.s_a}
                sV={thresholds?.s_v}
                observedRate={simulation?.telemetry.mismatch_rate}
                attackActive={attackActive}
              />
              {variant === "PNS" && (
                <p className="mt-3 rounded-md border border-sky-500/30 bg-sky-500/5 px-3 py-2 text-xs text-sky-200">
                  A PNS attack leaves the signature tokens untouched, so this curve stays on the baseline. The attack is caught by
                  the decoy-state rule: decoy detections fell outside their acceptance interval and Y₁ᴸ ≤ 0.
                </p>
              )}
            </Card>
          </div>
        </div>

        <footer className="mt-10 border-t border-quantum-700 pt-4 text-center font-mono text-[11px] text-slate-600">
          Qiskit-Aer density-matrix engine · ETSI GS QKD 014 · Chernoff-Hoeffding &amp; exact binomial bounds · no AI/ML
        </footer>
      </div>
    </div>
  );
}
