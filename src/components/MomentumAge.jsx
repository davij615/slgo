import { C } from "./palette.js";

const tkOf = (s) => (s ? s.split(":").pop() : "");

export default function MomentumAge({ data }) {
  if (!data || !data.rows) return null;
  const rows = data.rows;
  const maxAge = Math.max(1, ...rows.map((r) => r.above200 || 0));
  const extended = rows.filter((r) => r.extended).length;

  return (
    <div>
      {data.sample && (
        <div className="banner">sample data — run <b>python engine/momentum_age.py</b> for a live read</div>
      )}
      <p className="block-sub">
        How long each current survivor has actually been trending. <b>Trend age</b> is the
        consecutive days it has closed above its 50- and 200-day averages (from price, available
        now). <b>Screen streak</b> is how many snapshot runs it has held its place in the screen
        (builds as the daily log accrues). Longer isn't automatically better — very extended moves
        are more reversal-prone, so <span style={{ color: C.gone }}>amber = late-stage</span>, watch
        for exhaustion.{extended > 0 && <> <b style={{ color: C.gone }}>{extended} look extended.</b></>}
      </p>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table className="surv age-table">
          <thead>
            <tr>
              <th>#</th><th className="l">Ticker</th><th className="l">Company</th>
              <th>Trend age (days &gt; 200-day)</th><th>&gt; 50-day</th>
              <th>6mo above 50</th><th>Screen streak</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.ticker} style={r.extended ? { background: C.goneDim } : undefined}>
                <td className="rank">{i + 1}</td>
                <td className="l tk">{tkOf(r.ticker)}{r.extended && <span className="late"> ▲ late</span>}</td>
                <td className="l co">{r.company}</td>
                <td>
                  <div className="age-cell">
                    <div className="age-track">
                      <div className="age-bar" style={{
                        width: `${Math.max(3, ((r.above200 || 0) / maxAge) * 100)}%`,
                        background: r.extended ? C.gone : C.live,
                      }} />
                    </div>
                    <span className="age-num">{r.above200 ?? "—"}d</span>
                  </div>
                </td>
                <td>{r.above50 ?? "—"}d</td>
                <td>{r.frac50_6m != null ? `${Math.round(r.frac50_6m * 100)}%` : "—"}</td>
                <td style={{ color: r.streak ? C.live : C.faint }}>{r.streak ? `${r.streak}d` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="block-sub" style={{ marginTop: 16 }}>
        Screen streak fills in once <code>snapshot.py</code> has run for a few days — it can only count
        days it has observed, so early on it understates true tenure. Trend age comes from price
        history and is accurate immediately.
      </p>
    </div>
  );
}
