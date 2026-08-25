import { useMemo, useState } from "react";
import { C } from "./palette.js";
import { buildBook, computeWeights, sizeBook } from "./portfolio.js";

const capFmt = (v) => (v >= 1e9 ? `$${(v / 1e9).toFixed(v >= 1e10 ? 0 : 1)}B` : `$${(v / 1e6).toFixed(0)}M`);
const tkOf = (s) => (s ? s.split(":").pop() : "");
const CAP_LINES = [[2e9, "$2B"], [5e9, "$5B"], [10e9, "$10B"]];

export default function BalancedBook({ data, account, groupKey = "sector", groupLabel = "Sector", health = false }) {
  const [capLine, setCapLine] = useState(10e9);
  const [conviction, setConviction] = useState(0.5);
  const [tilt, setTilt] = useState(0);

  const { picks, sized, cash, largeShare } = useMemo(() => {
    const picks = buildBook(data.rows || [], capLine, groupKey);
    const weights = computeWeights(picks, { conviction, tilt });
    const { rows, cash } = sizeBook(picks, weights, account);
    const largeShare = rows.reduce((s, r) => s + (r.tier === "large" ? r.weight : 0), 0);
    return { picks, sized: rows, cash, largeShare };
  }, [data.rows, capLine, conviction, tilt, account, groupKey]);

  const byGroup = {};
  sized.forEach((r) => { (byGroup[r.group] ||= []).push(r); });
  const groups = Object.entries(byGroup).sort(
    (a, b) => Math.max(...b[1].map((r) => r.score || 0)) - Math.max(...a[1].map((r) => r.score || 0)));
  const nLarge = sized.filter((r) => r.tier === "large").length;
  const nSmall = sized.filter((r) => r.tier === "small").length;

  return (
    <div>
      <p className="block-sub">
        One best large-cap and one best small-cap per {groupLabel.toLowerCase()} (by composite score),
        so the book spans the whole {health ? "sector" : "market"} at both size ends instead of
        concentrating in one group. Weights are conviction-tilted and adjustable — a sensible
        diversified construction, not a proven-optimal one.
      </p>

      <div className="book-controls card">
        <div className="ctl">
          <span className="ctl-label">Large / small line</span>
          <span className="seg">
            {CAP_LINES.map(([v, lbl]) => (
              <button key={v} className={`nbtn ${capLine === v ? "on" : ""}`} onClick={() => setCapLine(v)}>{lbl}</button>
            ))}
          </span>
        </div>
        <div className="ctl">
          <span className="ctl-label">Conviction <b>{Math.round(conviction * 100)}%</b></span>
          <input type="range" min="0" max="1" step="0.05" value={conviction} onChange={(e) => setConviction(+e.target.value)} />
          <span className="ctl-ends">equal · score-weighted</span>
        </div>
        <div className="ctl">
          <span className="ctl-label">Size tilt <b>{tilt === 0 ? "neutral" : tilt > 0 ? `+${Math.round(tilt * 100)}% large` : `+${Math.round(-tilt * 100)}% small`}</b></span>
          <input type="range" min="-0.6" max="0.6" step="0.05" value={tilt} onChange={(e) => setTilt(+e.target.value)} />
          <span className="ctl-ends">small · large</span>
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden", marginTop: 14 }}>
        <table className="surv book-table">
          <thead>
            <tr>
              <th className="l">{groupLabel}</th><th className="l">Tier</th><th className="l">Ticker</th>
              <th className="l">Company</th><th>Cap</th><th>Score</th><th>Weight</th><th>Shares</th><th>Value</th>
            </tr>
          </thead>
          <tbody>
            {groups.map(([group, rows]) =>
              rows.sort((a, b) => (a.tier === "large" ? -1 : 1)).map((r, i) => (
                <tr key={r.symbol || r.name}>
                  <td className="l ind">{i === 0 ? group : ""}</td>
                  <td className="l"><span className={`tier ${r.tier}`}>{r.tier}</span></td>
                  <td className="l tk">{tkOf(r.symbol) || r.name}</td>
                  <td className="l co">{r.description || r.company}</td>
                  <td>{capFmt(r.market_cap_basic || 0)}</td>
                  <td style={{ color: C.gone }}>{r.score?.toFixed(2)}</td>
                  <td>
                    <div className="wt-cell">
                      <div className="wt-track"><div className="wt-bar" style={{ width: `${r.weight * 100}%` }} /></div>
                      <span className="wt-num">{(r.weight * 100).toFixed(0)}%</span>
                    </div>
                  </td>
                  <td className="buy">{r.shares}</td>
                  <td>${r.value.toFixed(0)}</td>
                </tr>
              )))}
          </tbody>
          <tfoot>
            <tr>
              <td className="l" colSpan={6} style={{ color: "var(--muted)" }}>
                {picks.length} names · {groups.length} {groupLabel.toLowerCase()}s · {nLarge} large / {nSmall} small ·
                large-cap share {(largeShare * 100).toFixed(0)}%
              </td>
              <td></td><td></td>
              <td style={{ color: "var(--muted)" }}>${cash.toFixed(0)} cash</td>
            </tr>
          </tfoot>
        </table>
      </div>

      <p className="block-sub" style={{ marginTop: 14 }}>
        {health
          ? "Diversifying across sub-sectors and cap sizes is the main defense against the biotech gap risk flagged above — no single trial readout sinks the book."
          : "Spreading one best large-cap and one best small-cap across every sector caps single-name and single-sector risk versus the concentrated top-N."}
        {" "}A group missing a tier simply contributes one name.
      </p>
    </div>
  );
}
