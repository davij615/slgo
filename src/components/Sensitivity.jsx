import { C } from "./palette.js";

const fmtVal = (knob, v) => {
  if (knob === "market_cap_min") return `$${(v / 1e9).toFixed(v < 1e9 ? 1 : 0)}B`;
  if (knob === "min_adv") return `$${(v / 1e6).toFixed(0)}M`;
  if (knob === "high_proximity") return `${(v * 100).toFixed(0)}%`;
  if (knob.includes("perf")) return `${v}%`;
  return `${v}`;
};

function Knob({ id, knob }) {
  const fragile = knob.swing > 0.4;
  return (
    <div className="card sens-card">
      <div className="sens-head">
        <span className="sens-label">{knob.label}</span>
        <span className={`sens-badge ${fragile ? "fragile" : "robust"}`}>
          {fragile ? "load-bearing" : "robust"} · swing {knob.swing.toFixed(2)}
        </span>
      </div>
      <div className="sens-rows">
        {knob.rows.map((r, i) => (
          <div className="sens-row" key={i}>
            <span className={`sens-val ${r.baseline ? "base" : ""}`}>
              ≥ {fmtVal(id, r.value)}{r.baseline ? " ●" : ""}
            </span>
            <div className="sens-track">
              <div className="sens-bar" style={{
                width: `${Math.max(2, r.jaccard * 100)}%`,
                background: r.jaccard >= 0.7 ? C.live : r.jaccard >= 0.4 ? C.gone : "#c0563f",
              }} />
            </div>
            <span className="sens-num">{(r.jaccard * 100).toFixed(0)}%</span>
            <span className="sens-count">{r.count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Sensitivity({ data }) {
  if (!data || !data.knobs) return null;
  const knobs = Object.entries(data.knobs);
  const fragileCount = knobs.filter(([, k]) => k.swing > 0.4).length;
  return (
    <div>
      {data.sample && (
        <div className="banner">sample data — run <b>python engine/sensitivity.py</b> for a live stability scan</div>
      )}
      <p className="block-sub">
        Baseline screen passes <b>{data.baseline_count}</b> names. Each bar shows how much the
        survivor set still overlaps the baseline as one threshold slides (● = current setting).
        Bars staying long = the exact number doesn't matter (robust). Bars that collapse =
        that knob is load-bearing and an overfitting suspect.
        {fragileCount > 0 && <> <b style={{ color: C.gone }}>{fragileCount} of {knobs.length} look load-bearing.</b></>}
      </p>
      <div className="sens-grid">
        {knobs.map(([id, knob]) => <Knob key={id} id={id} knob={knob} />)}
      </div>
      <p className="block-sub" style={{ marginTop: 18 }}>
        Note: this measures set <i>stability</i> on live data, not returns — it can't tell you a
        threshold is <i>profitable</i>, only whether the screen is sensitive to it. A robust knob
        means you're not curve-fitting that number; a fragile one deserves an ex-ante reason, not a
        tuned value.
      </p>
    </div>
  );
}
