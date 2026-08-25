"""
backtest.py — event-driven backtester for the momentum engine.

Tests the part that CAN be tested honestly: the price-based composite ranking
(risk-adjusted 12-1 momentum + 52-week-high + optional sector-relative). It does
NOT reconstruct the fundamental/ratings screen — that needs point-in-time data we
can't get, and a survivor-only version would be badly upward-biased (the research
put comparable bias at ~5%/yr). So this is the "price-proxy backtest" the
validation brief recommended, with the significance layer (PSR / MinTRL / deflated
Sharpe) built into the output so a lucky curve can't masquerade as edge.

Mechanics: signal computed on the rebalance day's close; orders filled at the NEXT
day's open (no lookahead); transaction cost + slippage on traded notional; marked
to close daily.

Two modes:
  strategy  — hold the top-N by composite, monthly rebalance (the actual book)
  signal    — long the top-decile by composite (tests the raw signal)

    python backtest.py --sample                          # synthetic demo (no network)
    python backtest.py --tickers universe.txt --start 2015-01-01   # live via yfinance

⚠️ A backtest on a fixed CURRENT ticker list is survivorship-biased (delisted names
missing). For an honest run, feed a point-in-time / delisting-inclusive universe.
Even then: in-sample results are not evidence — read the deflated Sharpe and MinTRL,
not the CAGR.
"""
import argparse
import json
import os
from datetime import date

import backtest_stats as st
import signals as sig

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "public", "backtest.json")

DEFAULTS = {
    "mode": "strategy", "top_n": 10, "top_quantile": 0.1, "rebalance": "M",
    "warmup": 252, "cost_bps": 5, "slip_bps": 10, "rf": 0.0, "capital": 100_000,
    "n_trials": 30,   # variants tried -> deflates the Sharpe
}


# ─────────────── price-based signals (pure) ───────────────
def mom_12_1_px(closes, i, lb=252, skip=21):
    if i - lb < 0:
        return None
    a, b = closes[i - skip], closes[i - lb]
    return a / b - 1 if a and b else None


def realized_vol_px(closes, i, win=126):
    if i - win < 0:
        return None
    rets = [closes[j] / closes[j - 1] - 1 for j in range(i - win + 1, i + 1) if closes[j - 1] and closes[j]]
    if len(rets) < 2:
        return None
    mu = sum(rets) / len(rets)
    return (sum((r - mu) ** 2 for r in rets) / len(rets)) ** 0.5 * (252 ** 0.5)


def high_52w_px(closes, i, win=252):
    lo = max(0, i - win + 1)
    window = [c for c in closes[lo:i + 1] if c]
    hi = max(window) if window else None
    return closes[i] / hi if closes[i] and hi else None


def score_universe(closes, i, universe, sectors):
    """Composite score per name as-of index i (uses data up to i, no lookahead)."""
    rows, names = [], []
    for t in universe:
        c = closes[t]
        if i >= len(c) or not c[i]:
            continue
        m = mom_12_1_px(c, i)
        if m is None:
            continue
        rows.append({"mom121": m, "vol": realized_vol_px(c, i),
                     "close": c[i], "high_52w": high_52w_px(c, i),
                     "sector": sectors.get(t) if sectors else None})
        names.append(t)
    if not rows:
        return {}
    scores = sig.composite_scores(rows)
    return dict(zip(names, scores))


# ─────────────── engine ───────────────
def rebalance_indices(dates, freq):
    """Indices at the last trading day of each month (or Friday for weekly)."""
    idx = []
    for i in range(len(dates) - 1):
        d, nxt = dates[i], dates[i + 1]
        if freq == "M" and d[5:7] != nxt[5:7]:
            idx.append(i)
        elif freq == "W" and d > nxt[:0] and _weeknum(d) != _weeknum(nxt):
            idx.append(i)
    return set(idx)


def _weeknum(d):
    import datetime
    return datetime.date.fromisoformat(d).isocalendar()[1]


def run(dates, closes, opens, bench, universe, sectors, cfg):
    n = len(dates)
    reb = rebalance_indices(dates, cfg["rebalance"])
    cash, shares = float(cfg["capital"]), {}
    equity, reb_equity, turnovers = [], [], []
    pending = None

    def px(t, i, use_open):
        arr = opens.get(t) if use_open else closes.get(t)
        v = arr[i] if arr and i < len(arr) else None
        return v or (closes[t][i] if closes.get(t) and closes[t][i] else None)

    for i in range(n):
        # 1) execute yesterday's orders at today's OPEN
        if pending is not None:
            pv = cash + sum(q * (closes[t][i] or 0) for t, q in shares.items())
            traded = 0.0
            new_shares = {}
            for t, w in pending.items():
                p = px(t, i, True)
                new_shares[t] = (pv * w) / p if p else 0
            for t in set(list(shares) + list(new_shares)):
                p = px(t, i, True)
                if not p:
                    new_shares[t] = shares.get(t, 0)
                    continue
                d = new_shares.get(t, 0) - shares.get(t, 0)
                traded += abs(d) * p
                cash -= d * p
            cash -= traded * (cfg["cost_bps"] + cfg["slip_bps"]) / 1e4
            shares = {t: q for t, q in new_shares.items() if q}
            turnovers.append(traded / pv if pv else 0)
            pending = None

        # 2) mark to close
        pv = cash + sum(q * (closes[t][i] or 0) for t, q in shares.items())
        equity.append(pv)

        # 3) on a rebalance day, compute targets from data up to i, fill next open
        if i in reb and i >= cfg["warmup"] and i + 1 < n:
            scores = score_universe(closes, i, universe, sectors)
            if scores:
                ranked = sorted(scores, key=lambda t: -scores[t])
                k = cfg["top_n"] if cfg["mode"] == "strategy" else max(1, int(len(ranked) * cfg["top_quantile"]))
                picks = ranked[:k]
                pending = {t: 1.0 / len(picks) for t in picks}
                reb_equity.append(pv)

    # benchmark buy-hold from first marked day
    b0 = next((b for b in bench if b), None)
    eq_bench = [equity[0] * (b / b0) if b and b0 else None for b in bench] if b0 else []
    period_rets = [reb_equity[j] / reb_equity[j - 1] - 1 for j in range(1, len(reb_equity))]

    s = st.summary(equity, period_rets=period_rets, rf=cfg["rf"], n_trials=cfg["n_trials"])
    s["turnover_annual"] = round((sum(turnovers) / len(turnovers) if turnovers else 0) *
                                 (12 if cfg["rebalance"] == "M" else 52), 3)
    if eq_bench and eq_bench[0]:
        bench_rets = st.to_returns([b for b in eq_bench if b])
        s["spy_cagr"] = round(st.cagr([b for b in eq_bench if b]) or 0, 4)
        s["spy_sharpe"] = round(st.sharpe(bench_rets, cfg["rf"]) or 0, 4)
        s["spy_max_drawdown"] = round(st.max_drawdown([b for b in eq_bench if b]), 4)
    return equity, eq_bench, s


def downsample(dates, equity, eq_bench, k=220):
    step = max(1, len(dates) // k)
    idx = list(range(0, len(dates), step))
    return ([dates[i] for i in idx],
            [round(equity[i], 2) for i in idx],
            [round(eq_bench[i], 2) if i < len(eq_bench) and eq_bench[i] else None for i in idx])


# ─────────────── data ───────────────
def load_yfinance(tickers, start, end):
    import yfinance as yf
    syms = list(dict.fromkeys(tickers + ["SPY"]))
    data = yf.download(syms, start=start, end=end, interval="1d",
                       auto_adjust=True, progress=False, group_by="ticker")
    dates = [d.strftime("%Y-%m-%d") for d in data.index]
    closes, opens = {}, {}
    for t in tickers:
        try:
            closes[t] = data[t]["Close"].tolist()
            opens[t] = data[t]["Open"].tolist()
        except Exception:
            pass
    bench = data["SPY"]["Close"].tolist()
    return dates, closes, opens, bench, list(closes.keys())


def synthetic():
    """Planted momentum: some names persistently trend, rest drift/mean-revert.
    Demonstrates the engine works; NOT evidence of anything."""
    import random
    rng = random.Random(42)
    ndays = 252 * 6
    dates = []
    y, m, d = 2019, 1, 1
    for _ in range(ndays):
        dates.append(f"{y:04d}-{m:02d}-{min(d,28):02d}")
        d += 1
        if d > 28:
            d = 1; m += 1
        if m > 12:
            m = 1; y += 1
    sectors = {}
    closes, opens = {}, {}
    universe = []
    for k in range(40):
        t = f"SYN{k:02d}"
        universe.append(t)
        sectors[t] = f"Sector{k % 6}"
        trend = k < 14          # 14 planted momentum names
        base = 50.0
        cl, op = [], []
        drift = 0.0
        for j in range(ndays):
            if trend and j % 120 == 0:
                drift = rng.uniform(0.0006, 0.0016)     # persistent up-regimes
            elif not trend:
                drift = rng.uniform(-0.0003, 0.0004)
            shock = rng.gauss(0, 0.018 if trend else 0.014)
            op.append(base)
            base *= 1 + drift + shock
            cl.append(base)
        closes[t], opens[t] = cl, op
    bench = []
    b = 100.0
    for j in range(ndays):
        b *= 1 + 0.0003 + rng.gauss(0, 0.009)     # market ~7.5%/yr
        bench.append(b)
    return dates, closes, opens, bench, universe, sectors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--tickers", help="file with one ticker per line")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--mode", choices=["strategy", "signal"], default="strategy")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()
    cfg = dict(DEFAULTS, mode=args.mode, top_n=args.top)

    if args.sample:
        dates, closes, opens, bench, universe, sectors = synthetic()
    else:
        tickers = [l.strip() for l in open(args.tickers)] if args.tickers else DEMO_UNIVERSE
        dates, closes, opens, bench, universe = load_yfinance(tickers, args.start, args.end)
        sectors = {}

    equity, eq_bench, s = run(dates, closes, opens, bench, universe, sectors, cfg)
    ds_dates, ds_eq, ds_bench = downsample(dates, equity, eq_bench)
    report = {"date": date.today().isoformat(), "mode": cfg["mode"], "config": cfg,
              "sample": args.sample, "start": dates[0], "end": dates[-1],
              "dates": ds_dates, "equity": ds_eq, "benchmark": ds_bench, "stats": s}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(report, open(OUT, "w"), separators=(",", ":"))
    print(f"Wrote {OUT}")
    print(f"  {cfg['mode']} | {dates[0]}..{dates[-1]} | CAGR {s['cagr']} vs SPY {s.get('spy_cagr')}")
    print(f"  Sharpe {s['sharpe']} | maxDD {s['max_drawdown']} | turnover {s['turnover_annual']}/yr")
    print(f"  PSR {s['psr_vs0']} | MinTRL {s['min_trl_obs']} obs | Deflated Sharpe {s['deflated_sharpe']} (N={s['n_trials']})")


DEMO_UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AVGO", "LLY",
                 "JPM", "XOM", "UNH", "V", "MA", "HD", "COST", "PG", "CAT", "GE"]

if __name__ == "__main__":
    main()
