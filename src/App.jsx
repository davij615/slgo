import { useEffect, useState, useCallback } from "react";
import Survivors from "./components/Survivors.jsx";
import Sensitivity from "./components/Sensitivity.jsx";
import MomentumAge from "./components/MomentumAge.jsx";
import BalancedBook from "./components/BalancedBook.jsx";
import MomentumViz from "./components/MomentumViz.jsx";
import Backtest from "./components/Backtest.jsx";

const BASE = import.meta.env.BASE_URL;

const STRATS = {
  screen: {
    label: "Conservative", endpoint: "/api/screen", apiFile: "screen.js", leaders: false,
    eyebrow: "survivors · rank-and-select · weekly",
    chips: ["Mkt cap > 500M", "Chg 1M > 5%", "Perf 1W > 0%", "ADX > 40", "Volatility < 5%", "Analyst Buy+", "ADV ≥ $5M"],
    blurb: "Every name cleared the conservative filters across the whole US market. Pick how many to hold and how to rank them — the composite favors steady, high-quality momentum.",
    nOpts: ["All", 5, 10, 20], nDefault: 20,
    methods: [["composite", "composite"], ["riskadj", "risk-adj"], ["mom121", "12-1"], ["chg", "1M chg"]],
  },
  aggr: {
    label: "Aggressive", endpoint: "/api/aggressive", apiFile: "aggressive.js", leaders: true,
    eyebrow: "momentum leaders · top-N · weekly",
    chips: ["No OTC", "Price ≥ $10", "Cap ≥ $1B", "ADV ≥ $20M", "above 50 > 200 MA", "near 52w high", "Perf 1M ≥ 10%", "ROE > 0"],
    blurb: "The strongest momentum leaders from the whole listed market, in a confirmed uptrend, ranked by the composite signal. Concentrated into the top names.",
    nOpts: [5, 10], nDefault: 5,
    methods: [["composite", "composite"], ["riskadj", "risk-adj"], ["mom121", "12-1"], ["raw", "raw"]],
  },
  health: {
    label: "Health", endpoint: "/api/health", apiFile: "health.js", leaders: true, health: true,
    eyebrow: "pharma · biotech · medtech · insurers · top-N",
    chips: ["Health Tech + Services", "No OTC", "Price ≥ $5", "Cap ≥ $300M", "ADV ≥ $3M", "above 50 > 200 MA", "Perf 1M ≥ 10%"],
    blurb: "Momentum leaders across the whole health universe — pharma, biotech, medical devices, digital health, hospitals, and health insurers. Biotech-tuned: lower size floors and no profitability gate, so pre-revenue names aren't excluded.",
    nOpts: [5, 10, 20], nDefault: 10,
    methods: [["composite", "composite"], ["riskadj", "risk-adj"], ["mom121", "12-1"], ["raw", "raw"]],
  },
};

export default function App() {
  const [mode, setMode] = useState("screen");
  const [n, setN] = useState(STRATS.screen.nDefault);
  const [method, setMethod] = useState("composite");
  const [account, setAccount] = useState(10000);
  const [view, setView] = useState("main");
  const [momStrategy, setMomStrategy] = useState("aggr");
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true); setErr(null); setData(null);
    if (mode === "sens" || mode === "age" || mode === "bt") {
      const file = mode === "sens" ? "sensitivity" : mode === "age" ? "momentum_age" : "backtest";
      fetch(`${BASE}${file}.json`)
        .then((r) => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
        .then(setData).catch((e) => setErr(e.message)).finally(() => setLoading(false));
      return;
    }
    if (mode === "mom") {
      const st = STRATS[momStrategy];
      fetch(`${st.endpoint}?n=12&method=composite`)
        .then((r) => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
        .then((d) => {
          const syms = (d.rows || []).map((x) => x.symbol).filter(Boolean);
          if (!syms.length) throw new Error("no picks to visualize");
          return fetch(`/api/momentum?symbols=${encodeURIComponent(syms.join(","))}`);
        })
        .then((r) => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
        .then((d) => { if (d.error) throw new Error(d.error); setData(d); })
        .catch((e) => setErr(e.message)).finally(() => setLoading(false));
      return;
    }
    const S = STRATS[mode];
    const book = view === "book";
    const params = new URLSearchParams({ method });
    if (book) params.set("full", "1");
    else if (n !== "All") params.set("n", n);
    fetch(`${S.endpoint}?${params}`)
      .then((r) => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then((d) => { if (d.error) throw new Error(d.error); setData(d); })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, [mode, n, method, view, momStrategy]);

  useEffect(() => { load(); }, [load]);

  const switchMode = (k) => {
    setMode(k);
    setData(null); setErr(null); setLoading(true); setView("main");
    if (STRATS[k]) {
      setN(STRATS[k].nDefault);
      if (!STRATS[k].methods.some(([m]) => m === method)) setMethod("composite");
    }
  };

  const S = STRATS[mode];
  const sens = mode === "sens";
  const age = mode === "age";
  const isScreen = !!S;
  const asOf = data?.asOf
    ? new Date(data.asOf).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" }) : "";

  const heroH1 = () => {
    if (sens) return <>How <em>fragile</em> is each filter?</>;
    if (age) return <>How long has each name <em>had momentum</em>?</>;
    if (mode === "mom") return <>Is the momentum <em>building or fizzling</em>?</>;
    if (mode === "bt") return <>Does the signal <em>hold up</em> in a backtest?</>;
    if (!data) return <>Your screen, <em>live</em>, across the whole US market.</>;
    if (mode === "health") return <>The {data.count} strongest <em>health</em> momentum leaders.</>;
    if (S.leaders) return <>The {data.count} strongest <em>momentum leaders</em> right now.</>;
    return n === "All" ? <>{data.count} stocks <em>pass the screen</em> right now.</>
      : <>Top {data.count}, <em>ranked</em> by {method}.</>;
  };

  return (
    <div className="wrap">
      <header className="masthead">
        <span className="brand">QUANT·LAB / <b>{sens ? "stability" : age ? "momentum age" : mode === "mom" ? "momentum" : mode === "bt" ? "backtest" : S.label.toLowerCase()}</b></span>
        <span className="meta">
          {(isScreen || mode === "mom" || mode === "bt") && data ? `as of ${asOf}` : "whole US market"}
          <button className="refresh" onClick={load} disabled={loading}>{loading ? "running…" : "↻ rerun"}</button>
        </span>
      </header>

      <div className="strat-toggle">
        {Object.entries(STRATS).map(([k, v]) => (
          <button key={k} className={`strat ${mode === k ? "on" : ""}`} onClick={() => switchMode(k)}>{v.label}</button>
        ))}
        <button className={`strat ${sens ? "on" : ""}`} onClick={() => switchMode("sens")}>Filter stability</button>
        <button className={`strat ${age ? "on" : ""}`} onClick={() => switchMode("age")}>Momentum age</button>
        <button className={`strat ${mode === "mom" ? "on" : ""}`} onClick={() => switchMode("mom")}>Momentum viz</button>
        <button className={`strat ${mode === "bt" ? "on" : ""}`} onClick={() => switchMode("bt")}>Backtest</button>
        {mode === "mom" && (
          <span className="topn">
            book
            {Object.entries(STRATS).map(([k, v]) => (
              <button key={k} className={`nbtn ${momStrategy === k ? "on" : ""}`} onClick={() => setMomStrategy(k)}>{v.label}</button>
            ))}
          </span>
        )}
        {isScreen && (
          <span className="topn">
            {!(view === "book") && <>
              top
              {S.nOpts.map((opt) => (
                <button key={opt} className={`nbtn ${n === opt ? "on" : ""}`} onClick={() => setN(opt)}>{opt}</button>
              ))}
            </>}
            <span style={{ marginLeft: 10 }}>rank</span>
            {S.methods.map(([k, lbl]) => (
              <button key={k} className={`nbtn ${method === k ? "on" : ""}`} onClick={() => setMethod(k)}>{lbl}</button>
            ))}
          </span>
        )}
      </div>

      <section className="hero">
        <div className="eyebrow">{sens ? "do the thresholds even matter?" : age ? "how long has it been trending?" : mode === "mom" ? "live momentum · multi-timeframe" : mode === "bt" ? "price-proxy backtest · significance-tested" : S.eyebrow}</div>
        <h1>{heroH1()}</h1>
        <p>{sens
          ? "Before trusting a threshold, see whether it's doing real work. This slides each gate across a range and shows how much the survivor set actually changes — robust knobs you can trust, fragile ones are overfitting suspects."
          : age
          ? "Which names are fresh breakouts and which have been running for a year. Trend age from price is available now; screen tenure accrues as the daily snapshot log fills in."
          : mode === "mom"
          ? `Live momentum strength across timeframes for the current ${STRATS[momStrategy].label} picks — see at a glance which are accelerating and which are rolling over.`
          : mode === "bt"
          ? "An event-driven backtest of the price-based composite signal, with the significance layer (probabilistic & deflated Sharpe, min track record) built in so a lucky curve can't pass for edge."
          : S.blurb}</p>
        {isScreen && <div className="chips-row">{S.chips.map((f) => <span className="fchip" key={f}>{f}</span>)}</div>}
      </section>

      {mode === "health" && (
        <div className="banner warn">
          <b>Biotech carries binary event risk.</b> FDA decisions and trial readouts can gap a name
          tens of percent overnight — momentum assumes trends persist; biotech can violate that in a
          single session, and no moving-average exit protects against a gap. This ranks leaders; it
          doesn't neutralize catalyst risk. Size down and diversify.
        </div>
      )}

      {isScreen && (
        <div className="subtoggle">
          {[["main", S.leaders ? "Leaders" : "Screen"], ["book", "Balanced book"]].map(([k, lbl]) => (
            <button key={k} className={`sub ${view === k ? "on" : ""}`} onClick={() => setView(k)}>{lbl}</button>
          ))}
        </div>
      )}

      <section className="block">
        <div className="block-head">
          <span className="num">→</span>
          <h2>{sens ? "Threshold sensitivity" : age ? "Trend age & screen tenure" : mode === "mom" ? `Momentum of the ${STRATS[momStrategy].label} picks` : mode === "bt" ? "Equity curve vs SPY"
            : (view === "book") ? "Balanced book"
            : (S.leaders || n !== "All" ? `Top ${n === "All" ? "" : n} this week` : "The portfolio for today")}</h2>
        </div>
        {loading && <p className="empty">{sens ? "Loading the stability scan…" : age ? "Loading the momentum-age read…" : mode === "mom" ? "Reading live momentum across timeframes…" : mode === "bt" ? "Loading the backtest…" : "Running the screen across the whole market…"}</p>}

        {err && (
          <div className="card errbox">
            <p style={{ marginTop: 0 }}>Couldn't load {sens ? "sensitivity.json" : age ? "momentum_age.json" : `the screen endpoint (${err})`}.</p>
            <p style={{ marginBottom: 0 }}>
              {sens || age
                ? <>Run <code>python engine/{sens ? "sensitivity" : "momentum_age"}.py</code> to generate it (<code>--sample</code> for a demo).</>
                : <>Live screens run through <code>/api</code> functions — deploy to Vercel, or use <code>vercel dev</code> locally (browsers can't call TradingView directly).</>}
            </p>
          </div>
        )}

        {data && !loading && (age
          ? <MomentumAge data={data} />
          : sens
          ? <Sensitivity data={data} />
          : mode === "mom"
          ? <MomentumViz data={data} />
          : mode === "bt"
          ? <Backtest data={data} />
          : (view === "book")
          ? <>
              <div className="sizing">
                <label>Capital $
                  <input type="number" min="0" step="1000" value={account}
                    onChange={(e) => setAccount(Math.max(0, +e.target.value))} />
                </label>
                <span className="sizing-note">conviction-weighted across the book</span>
              </div>
              <BalancedBook data={data} account={account}
                groupKey={mode === "health" ? "industry" : "sector"}
                groupLabel={mode === "health" ? "Sub-industry" : "Sector"}
                health={mode === "health"} />
            </>
          : data.count === 0
            ? <p className="empty">Nothing passes right now — these filters are strict. Loosen one in <code>api/{S.apiFile}</code>.</p>
            : <>
                {mode === "health" && data.mix && (
                  <div className="chips-row mix">
                    {Object.entries(data.mix).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                      <span className="fchip" key={k}>{k} · {v}</span>
                    ))}
                  </div>
                )}
                <div className="sizing">
                  <label>Capital $
                    <input type="number" min="0" step="1000" value={account}
                      onChange={(e) => setAccount(Math.max(0, +e.target.value))} />
                  </label>
                  <span className="sizing-note">equal weight across {data.count} · integer shares</span>
                </div>
                <p className="block-sub">
                  {S.leaders
                    ? `Top ${data.count} of ${data.total} qualifiers, ranked by ${method}.`
                    : (n === "All" ? `${data.count} survivors.` : `Top ${data.count} of ${data.total} survivors, ranked by ${method}.`)}
                  {" "}The email sheet adds the buy/sell/hold diff vs. last week.
                </p>
                <Survivors data={data} account={account} maxPos={data.count} mode={mode} />
              </>
        )}
      </section>

      <footer>
        Three strategies + stability & momentum-age scans, one engine · live via TradingView, whole US market.<br />
        Screens in <code>api/screen.js</code> / <code>aggressive.js</code> / <code>health.js</code>; shared ranking in <code>api/_signals.js</code>.<br />
        Research tooling, not investment advice.
      </footer>
    </div>
  );
}
