/**
 * Visualizer.jsx — Measurement Distribution Visualizer.
 *
 * Plots the exact binomial distribution of Bob's projective-measurement
 * mismatch rate for the calibrated honest channel (baseline) and for the
 * latest session (observed), with vertical ReferenceLines at s_a and s_v.
 * An attack shows up as the observed curve jumping right, past s_v.
 *
 * Props
 *   data          mismatch_distribution: [{ mismatch_rate, baseline, observed }]
 *   sA, sV        thresholds (0 <= s_a < s_v < 0.5)
 *   observedRate  measured mismatch rate of the session (optional marker)
 *   attackActive  colours the observed curve red
 *   width/height  fixed size (tests); omit width for a responsive chart
 */
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const X_DOMAIN_MAX = 0.6;
const X_TICKS = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6];

/** Probability mass of a series strictly beyond x (the curve "past" a threshold). */
export function massBeyond(data, x, key = "observed") {
  return (data ?? []).reduce((total, point) => (point.mismatch_rate > x ? total + (point[key] ?? 0) : total), 0);
}

const percent = (value, digits = 1) => `${(value * 100).toFixed(digits)}%`;

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-quantum-600 bg-quantum-900/95 px-3 py-2 font-mono text-xs text-slate-200 shadow-xl">
      <div className="mb-1 text-slate-400">mismatch rate {percent(label, 2)}</div>
      {payload.map((entry) => (
        <div key={entry.dataKey} style={{ color: entry.color }}>
          {entry.name}: {entry.value.toExponential(2)}
        </div>
      ))}
    </div>
  );
}

function DistributionChart({ data, sA, sV, observedRate, attackActive, width, height }) {
  const observedColor = attackActive ? "#f43f5e" : "#22d3ee";
  return (
    <AreaChart data={data} width={width} height={height} margin={{ top: 24, right: 24, bottom: 8, left: 8 }}>
      <defs>
        <linearGradient id="dtpt-baseline" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#34d399" stopOpacity={0.45} />
          <stop offset="100%" stopColor="#34d399" stopOpacity={0} />
        </linearGradient>
        <linearGradient id="dtpt-observed" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={observedColor} stopOpacity={0.55} />
          <stop offset="100%" stopColor={observedColor} stopOpacity={0} />
        </linearGradient>
      </defs>

      <CartesianGrid stroke="#1c2536" strokeDasharray="3 3" />
      <ReferenceArea x1={sA} x2={sV} fill="#f59e0b" fillOpacity={0.06} ifOverflow="visible" />
      <ReferenceArea x1={sV} x2={X_DOMAIN_MAX} fill="#f43f5e" fillOpacity={0.05} ifOverflow="visible" />

      <XAxis
        dataKey="mismatch_rate"
        type="number"
        domain={[0, X_DOMAIN_MAX]}
        ticks={X_TICKS}
        tickFormatter={(value) => percent(value, 0)}
        stroke="#64748b"
        tick={{ fontSize: 11 }}
        label={{ value: "Projective mismatch rate", position: "insideBottom", offset: -4, fill: "#64748b", fontSize: 11 }}
        height={40}
      />
      <YAxis stroke="#64748b" tick={{ fontSize: 11 }} tickFormatter={(value) => value.toFixed(3)} width={52} />
      <Tooltip content={<ChartTooltip />} />
      <Legend verticalAlign="top" height={24} wrapperStyle={{ fontSize: 12, color: "#cbd5e1" }} />

      <Area
        type="monotone"
        dataKey="baseline"
        name="Honest baseline"
        stroke="#34d399"
        strokeWidth={2}
        fill="url(#dtpt-baseline)"
        isAnimationActive
        animationDuration={500}
      />
      <Area
        type="monotone"
        dataKey="observed"
        name={attackActive ? "Observed (under attack)" : "Observed session"}
        stroke={observedColor}
        strokeWidth={2}
        fill="url(#dtpt-observed)"
        isAnimationActive
        animationDuration={900}
        animationEasing="ease-out"
      />

      <ReferenceLine
        x={sA}
        stroke="#f59e0b"
        strokeWidth={2}
        strokeDasharray="6 3"
        ifOverflow="extendDomain"
        label={{ value: `s_a ${percent(sA)}`, position: "insideTopRight", fill: "#f59e0b", fontSize: 11 }}
      />
      <ReferenceLine
        x={sV}
        stroke="#f43f5e"
        strokeWidth={2}
        ifOverflow="extendDomain"
        label={{ value: `s_v ${percent(sV)}`, position: "insideTopLeft", fill: "#f43f5e", fontSize: 11 }}
      />
      {Number.isFinite(observedRate) && (
        <ReferenceLine
          x={observedRate}
          stroke="#e2e8f0"
          strokeDasharray="2 4"
          ifOverflow="extendDomain"
          label={{ value: "measured", position: "insideBottomRight", fill: "#94a3b8", fontSize: 10 }}
        />
      )}
    </AreaChart>
  );
}

export default function Visualizer({ data = [], sA, sV, observedRate, attackActive = false, width, height = 320 }) {
  const hasData = data.length > 0 && Number.isFinite(sA) && Number.isFinite(sV);
  const beyondSv = hasData ? massBeyond(data, sV) : 0;

  if (!hasData) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-dashed border-quantum-600 text-sm text-slate-500"
        style={{ height }}
      >
        Awaiting measurement distribution…
      </div>
    );
  }

  const chart = (
    <DistributionChart
      data={data}
      sA={sA}
      sV={sV}
      observedRate={observedRate}
      attackActive={attackActive}
      width={width}
      height={height}
    />
  );

  return (
    <div data-testid="measurement-visualizer">
      {width ? chart : <ResponsiveContainer width="100%" height={height}>{chart}</ResponsiveContainer>}
      <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 font-mono text-xs text-slate-400">
        <span>
          s_a = <span className="text-amber-400">{percent(sA, 2)}</span>
        </span>
        <span>
          s_v = <span className="text-rose-400">{percent(sV, 2)}</span>
        </span>
        <span data-testid="mass-beyond-sv">
          observed mass beyond s_v ={" "}
          <span className={beyondSv > 0.5 ? "font-semibold text-rose-400" : "text-emerald-400"}>{percent(beyondSv)}</span>
        </span>
      </div>
    </div>
  );
}
