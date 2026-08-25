import { C } from "./palette.js";

const STATE = {
  accelerating: { c: C.live, label: "accelerating" },
  steady: { c: "#5b8def", label: "steady" },
  fading: { c: C.gone, label: "fading" },
  reversing: { c: "#c0563f", label: "reversing" },
};
const tkOf = (s) => (s ? s.split(":").pop() : "");
const pct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`);

// term-structure sparkline: monthly-rate at [1Y,6M,3M,1M,1W], recent on the right
function Spark({ rates, color }) {
  const order = [rates.y, rates.m6, rates.m3, rates.m1, rates.w];
  const vals = order.filter((v) => v != null);
  if (vals.length < 2) return <div className="spark-empty">—</div>;
  const W = 208, H = 46, pad = 6;
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  const span = hi - lo || 1;
  const x = (i) => pad + (i * (W - 2 * pad)) / (order.length - 1);
  const y = (v) => H - pad - ((v - lo) / span) * (H - 2 * pad);
  const pts = order.map((v, i) => (v == null ? null : `${x(i)},${y(v)}`)).filter(Boolean).join(" ");
  const zeroY = y(0);
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <line x1={pad} x2={W - pad} y1={zeroY} y2={zeroY} stroke={C.rule} strokeWidth="1" strokeDasharray="2 3" />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
      {order.map((v, i) => v == null ? null : (
        <circle key={i} cx={x(i)} cy={y(v)} r={i === order.length - 1 ? 3.5 : 2}
          fill={i === order.length - 1 ? color : "var(--bg)"} stroke={color} strokeWidth="1.5" />
      ))}
    </svg>
  );
}

function Row({ r }) {
  const st = STATE[r.state] || STATE.steady;
  return (
    <div className="mom-row card">
      <div className="mom-id">
        <div className="mom-tk">{tkOf(r.symbol) || r.ticker}
          <span className="mom-badge" style={{ color: st.c, background: `${st.c}22` }}>{st.label}</span>
          {r.fizzling && <span className="mom-fizz">⚠ fizzling</span>}
        </div>
        <div className="mom-co">{r.company}</div>
        <div className="mom-ctx">
          str <b style={{ color: st.c }}>{r.strength}</b> · accel {r.accel > 0 ? "+" : ""}{r.accel}/mo
          {r.adx != null && <> · ADX {r.adx}</>}{r.rsi != null && <> · RSI {r.rsi}</>}
          {r.fromHigh != null && <> · {r.fromHigh <= 0 ? "at high" : `${r.fromHigh}% off high`}</>}
        </div>
      </div>

      <div className="mom-spark">
        <Spark rates={r.rates} color={st.c} />
        <div className="mom-axis"><span>1Y</span><span>6M</span><span>3M</span><span>1M</span><span>1W</span></div>
      </div>

      <div className="mom-perf">
        {[["1W", r.perf.w], ["1M", r.perf.m1], ["3M", r.perf.m3], ["6M", r.perf.m6], ["1Y", r.perf.y]].map(([k, v]) => (
          <div className="mom-pf" key={k}>
            <span className="k">{k}</span>
            <span className="v" style={{ color: v == null ? C.faint : v >= 0 ? C.live : C.gone }}>{pct(v)}</span>
          </div>
        ))}
      </div>

      <div className="mom-strength">
        <div className="str-track"><div className="str-bar" style={{ width: `${r.strength}%`, background: st.c }} /></div>
        <span className="str-num">{r.strength}</span>
      </div>
    </div>
  );
}

export default function MomentumViz({ data }) {
  if (!data || !data.rows) return null;
  const n = data.rows.length;
  const fizz = data.rows.filter((r) => r.fizzling).length;
  const acc = data.rows.filter((r) => r.state === "accelerating").length;
  return (
    <div>
      <p className="block-sub">
        Each line is the stock's momentum <b>rate</b> across timeframes, normalized to a per-month
        pace — oldest (1Y) on the left, most recent (1W) on the right. A line <b>rising to the
        right</b> is accelerating; <b>falling</b> is fading; <b>dropping below zero</b> on the right is
        reversing. Strength (0–100) blends trend strength (ADX) with how many windows are still positive.
        {" "}<b style={{ color: C.live }}>{acc} accelerating</b>, <b style={{ color: C.gone }}>{fizz} fizzling</b> of {n}.
      </p>
      <div className="mom-list">
        {data.rows.map((r) => <Row key={r.symbol || r.ticker} r={r} />)}
      </div>
      <p className="block-sub" style={{ marginTop: 14 }}>
        Rates come from trailing cumulative returns divided by window length, so they're a smoothed
        read, not a tick-by-tick feed — the shape (accelerating vs fading) is the signal, not the
        exact per-month number. "Fizzling" fires when the recent pace has turned down and price has
        slipped below its 20-day line.
      </p>
    </div>
  );
}
