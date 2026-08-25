import { C } from "./palette.js";

const fmtCap = (v) =>
  v >= 1e9 ? `${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(0)}M` : `${v}`;
const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`);
const tk = (sym, name) => (sym ? sym.split(":").pop() : name);
const fmtScore = (v) =>
  v == null ? "—" : Math.abs(v) >= 10 ? v.toFixed(0) : v.toFixed(2);

function analystLabel(mark) {
  if (mark == null) return "—";
  if (mark <= 1.5) return "Strong Buy";
  if (mark < 2.5) return "Buy";
  return "Hold";
}

export default function Survivors({ data, account, maxPos, mode }) {
  const aggr = mode === "aggr" || mode === "health";
  const sized = account > 0 && maxPos > 0;
  const rows = sized ? data.rows.slice(0, maxPos) : data.rows;
  const dollarsEach = sized && rows.length ? account / rows.length : 0;

  let deployed = 0;
  const withShares = rows.map((r) => {
    const price = r.close || 0;
    const shares = sized && price > 0 ? Math.floor(dollarsEach / price) : null;
    const value = shares ? shares * price : 0;
    deployed += value;
    return { ...r, shares, value };
  });

  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <table className="screen-table">
        <thead>
          <tr>
            <th className="rk">#</th>
            <th className="l">Ticker</th>
            <th className="l">Company</th>
            <th>Price</th>
            <th>Mkt cap</th>
            {aggr ? <th>Perf 1M</th> : <th>Chg 1M</th>}
            {aggr ? <th>12-1 mom</th> : <th>Perf 1W</th>}
            <th>ADX</th>
            {!aggr && <th>Vol</th>}
            {sized && <th>Shares</th>}
            {sized && <th>Value</th>}
            <th>Score</th>
          </tr>
        </thead>
        <tbody>
          {withShares.map((r, i) => (
            <tr key={r.symbol || i}>
              <td className="rk">{i + 1}</td>
              <td className="l tkr">{tk(r.symbol, r.name)}</td>
              <td className="l co" title={r.description}>{r.description}
                {r.industry && <span className="subind">{r.industry}</span>}
              </td>
              <td>${r.close?.toFixed(2)}</td>
              <td>{fmtCap(r.market_cap_basic)}</td>
              <td style={{ color: C.live }}>{pct(aggr ? r["Perf.1M"] : r["change|1M"])}</td>
              <td style={aggr ? { color: C.live } : undefined}>{aggr ? pct(r.mom121) : pct(r["Perf.W"])}</td>
              <td>{r.ADX?.toFixed(0)}</td>
              {!aggr && <td>{r["Volatility.D"]?.toFixed(1)}%</td>}
              {sized && <td className="buy">{r.shares ?? "—"}</td>}
              {sized && <td>${r.value.toFixed(0)}</td>}
              <td style={{ color: C.gone, fontWeight: 600 }}>{fmtScore(r.score)}</td>
            </tr>
          ))}
        </tbody>
        {sized && (
          <tfoot>
            <tr>
              <td colSpan={aggr ? 8 : 9} className="l" style={{ color: "var(--muted)" }}>
                Equal weight · {withShares.length} positions
              </td>
              <td className="buy">{withShares.reduce((a, r) => a + (r.shares || 0), 0)}</td>
              <td>${deployed.toFixed(0)}</td>
              <td className="l" style={{ color: "var(--muted)" }}>
                ${(account - deployed).toFixed(0)} cash
              </td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}
