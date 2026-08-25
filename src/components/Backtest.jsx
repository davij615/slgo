import { C } from "./palette.js";

const pct = (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
const num = (v) => (v == null ? "—" : v.toFixed(2));

function Curve({ dates, equity, benchmark }) {
  const s0 = equity.find((v) => v != null);
  const b0 = benchmark.find((v) => v != null);
  const strat = equity.map((v) => (v == null || !s0 ? null : (v / s0) * 100));
  const bench = benchmark.map((v) => (v == null || !b0 ? null : (v / b0) * 100));
  const all = [...strat, ...bench].filter((v) => v != null);
  const lo = Math.min(...all), hi = Math.max(...all);
  const W = 720, H = 260, pad = 34, span = hi - lo || 1;
  const x = (i) => pad + (i * (W - pad - 10)) / (strat.length - 1);
  const y = (v) => H - pad - ((v - lo) / span) * (H - pad - 12);
  const path = (arr) => arr.map((v, i) => (v == null ? null : `${i === 0 || arr[i - 1] == null ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)).filter(Boolean).join(" ");
  const base100 = y(100);
  return (
    <svg className="bt-curve" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
      <line x1={pad} x2={W - 10} y1={base100} y2={base100} stroke={C.rule} strokeWidth="1" strokeDasharray="2 3" />
      <text x={pad - 6} y={base100 + 3} textAnchor="end" fill={C.faint} fontSize="10" fontFamily="monospace">100</text>
      <text x={pad - 6} y={y(hi) + 3} textAnchor="end" fill={C.faint} fontSize="10" fontFamily="monospace">{hi.toFixed(0)}</text>
      <text x={pad - 6} y={y(lo) + 3} textAnchor="end" fill={C.faint} fontSize="10" fontFamily="monospace">{lo.toFixed(0)}</text>
      <path d={path(bench)} fill="none" stroke={C.muted} strokeWidth="1.5" opacity="0.8" />
      <path d={path(strat)} fill="none" stroke={C.live} strokeWidth="2" />
      <text x={pad} y={H - 6} fill={C.faint} fontSize="10" fontFamily="monospace">{dates[0]}</text>
      <text x={W - 10} y={H - 6} textAnchor="end" fill={C.faint} fontSize="10" fontFamily="monospace">{dates[dates.length - 1]}</text>
    </svg>
  );
}

function Stat({ label, value, sub, tone }) {
  return (
    <div className="bt-stat">
      <div className="bt-stat-v" style={tone ? { color: tone } : undefined}>{value}</div>
      <div className="bt-stat-l">{label}</div>
      {sub && <div className="bt-stat-s">{sub}</div>}
    </div>
  );
}

export default function Backtest({ data }) {
  if (!data || !data.stats) return null;
  const s = data.stats;
  const yrs = s.min_trl_obs ? (s.min_trl_obs / 252).toFixed(1) : null;
  const haveYrs = ((data.equity?.length || 0)); // downsampled; use span text instead
  const dsrTone = s.deflated_sharpe == null ? C.muted : s.deflated_sharpe >= 0.9 ? C.live : s.deflated_sharpe >= 0.5 ? C.gone : "#c0563f";
  const beat = s.cagr != null && s.spy_cagr != null ? s.cagr - s.spy_cagr : null;

  return (
    <div>
      {data.sample && (
        <div className="banner warn"><b>Synthetic demo data.</b> This curve is planted momentum on
          fake prices to prove the engine runs — it is <b>not evidence of anything</b>. Run
          <b> python engine/backtest.py</b> with a real universe for live results.</div>
      )}
      <p className="block-sub">
        {data.mode && data.mode.startsWith("combined")
          ? "Combined book — top 5 from each of Conservative + Aggressive + Health, inverse-volatility weighted"
          : data.mode === "signal" ? "Top-decile composite signal" : "Top-N composite strategy"},
        {" "}{data.start} → {data.end},
        {" "}{data.config?.rebalance === "W" ? "weekly (Mon) rebalance" : "monthly rebalance"},
        {data.engine ? ` · engine: ${data.engine}` : ", next-open fills"},
        {" "}{data.config?.cost_bps + data.config?.slip_bps}bps round-trip cost. Green = strategy,
        grey = SPY (both indexed to 100).
      </p>

      <div className="card" style={{ padding: "14px 12px" }}><Curve dates={data.dates} equity={data.equity} benchmark={data.benchmark} /></div>

      <div className="bt-grid">
        <Stat label="CAGR" value={pct(s.cagr)} sub={s.spy_cagr != null ? `SPY ${pct(s.spy_cagr)}` : null} tone={beat > 0 ? C.live : beat < 0 ? C.gone : null} />
        <Stat label="Sharpe" value={num(s.sharpe)} sub={s.spy_sharpe != null ? `SPY ${num(s.spy_sharpe)}` : null} />
        <Stat label="Sortino" value={num(s.sortino)} />
        <Stat label="Max drawdown" value={pct(s.max_drawdown)} sub={s.spy_max_drawdown != null ? `SPY ${pct(s.spy_max_drawdown)}` : null} />
        <Stat label="Calmar" value={num(s.calmar)} />
        <Stat label="Turnover" value={s.turnover_annual != null ? `${s.turnover_annual}×/yr` : "—"} />
        {s.trades != null && <Stat label="Trades" value={s.trades} sub="closed round-trips" />}
        {s.hit_rate != null && <Stat label="Hit rate" value={pct(s.hit_rate)} sub="rebalance periods +" />}
      </div>

      <div className="block-head" style={{ marginTop: 24 }}>
        <span className="num">✓</span><h2>Is it real? (significance)</h2>
      </div>
      <p className="block-sub">
        The numbers above are easy to fool yourself with. These three ask whether the record could be luck.
      </p>
      <div className="bt-grid sig">
        <Stat label="Probabilistic Sharpe" value={s.psr_vs0 != null ? `${(s.psr_vs0 * 100).toFixed(0)}%` : "—"}
          sub="prob. true Sharpe > 0" tone={s.psr_vs0 >= 0.95 ? C.live : C.gone} />
        <Stat label="Deflated Sharpe" value={s.deflated_sharpe != null ? `${(s.deflated_sharpe * 100).toFixed(0)}%` : "—"}
          sub={`after N=${s.n_trials} variants tried`} tone={dsrTone} />
        <Stat label="Min track record" value={yrs ? `${yrs} yr` : "—"}
          sub="needed for 95% confidence" tone={C.muted} />
      </div>

      <p className="block-sub" style={{ marginTop: 16 }}>
        <b>How to read it:</b> a high CAGR means nothing if the <b>deflated Sharpe</b> is low — that means
        once you count the {s.n_trials} filter/ranking variants already tried, a record this good is
        roughly what you'd expect from luck alone. And if the <b>min track record</b> exceeds the length
        you actually have, the Sharpe isn't yet statistically distinguishable from zero. Even at their
        best, in-sample backtests overstate live results; the price-proxy can't see the fundamental
        screen, and a fixed current universe carries survivorship bias. This is a sanity check on the
        engine, not proof it makes money — only the forward paper record settles that.
      </p>
    </div>
  );
}
