"""
bt_combined.py — the combined book on BACKTRADER (mementum/backtrader).

Why backtrader: unlike a single-symbol tool, it holds the whole portfolio — many
data feeds, cross-sectional rebalancing, a realistic broker (commission + slippage),
and battle-tested analyzers. The integration points with this repo:
  • the RANKING reuses signals.composite_scores (same math as the live screens)
  • the RESULTS are scored by backtest_stats (same PSR / deflated-Sharpe layer)
  • the OUTPUT is written to public/backtest.json, so the dashboard's Backtest tab
    renders the backtrader run with no other changes.

Strategy: each rebalance (monthly default / weekly-Mon), from the loaded universe
take the top 5 of each sleeve (Conservative = uptrend + positive 12-1 momentum;
Aggressive = full trend stack near 52w high; Health = health-sector + positive
momentum), union them, INVERSE-VOLATILITY weight, hold to next rebalance.

    pip install backtrader yfinance pandas numpy
    python bt_combined.py --sample                       # synthetic (no network)
    python bt_combined.py --universe universe.csv --start 2016-01-01 --rebalance M

HONEST LIMITS: price/sector proxy of the screens (no live ROE/rating gates);
survivorship-biased on a fixed universe; in-sample overstates live. Read the
deflated Sharpe and turnover, not the CAGR. Not investment advice.
"""
from __future__ import annotations
import argparse
import json
import os

# --- defensive shim so backtrader imports on modern Python (collections.abc) ---
import collections
import collections.abc
for _n in ("Iterable", "Mapping", "MutableMapping", "Sequence"):
    if not hasattr(collections, _n):
        setattr(collections, _n, getattr(collections.abc, _n))

import numpy as np
import pandas as pd
import backtrader as bt

import signals as sig
import backtest_stats as st

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "public", "backtest.json")
HEALTH_SET = {"Health Technology", "Health Services", "Health", "Healthcare"}
LOOKBACK, SKIP, VOL_WIN, TOP_N, HIGH_PROX = 252, 21, 126, 5, 0.75


class ValueRecorder(bt.Analyzer):
    """Records the portfolio value each bar so we can rebuild the equity curve."""
    def start(self):
        self.dates, self.values = [], []

    def next(self):
        self.dates.append(self.strategy.datas[0].datetime.date(0).isoformat())
        self.values.append(self.strategy.broker.getvalue())

    def get_analysis(self):
        return {"dates": self.dates, "values": self.values}


class CombinedBook(bt.Strategy):
    params = dict(rebalance="M", sectors=None, top_n=TOP_N, high_prox=HIGH_PROX)

    def __init__(self):
        self.sectors = self.p.sectors or {}
        self._last = None
        self._feeds = {d._name: d for d in self.datas}

    def _key(self, dt):
        return (dt.year, dt.month) if self.p.rebalance == "M" else dt.isocalendar()[:2]

    def _metrics(self, d):
        c = d.close
        if len(d) <= LOOKBACK:
            return None
        try:
            mom = c[-SKIP] / c[-LOOKBACK] - 1
            rets = [c[-j] / c[-j - 1] - 1 for j in range(VOL_WIN) if c[-j - 1]]
            vol = float(np.std(rets) * np.sqrt(252)) if len(rets) > 1 else np.nan
            hi = max(c[-j] for j in range(LOOKBACK))
            high = c[0] / hi if hi else np.nan
            s50 = float(np.mean([c[-j] for j in range(50)]))
            s200 = float(np.mean([c[-j] for j in range(200)]))
            return dict(mom=mom, vol=vol, high=high, close=c[0], s50=s50, s200=s200)
        except Exception:
            return None

    def _rank(self, cand, M):
        cand = [t for t in cand if not np.isnan(M[t]["mom"])]
        if not cand:
            return []
        rows = [{"mom121": M[t]["mom"], "vol": M[t]["vol"], "close": M[t]["close"],
                 "high_52w": M[t]["high"], "sector": self.sectors.get(t)} for t in cand]
        sc = sig.composite_scores(rows)
        order = sorted(range(len(cand)), key=lambda j: -(sc[j] if sc[j] is not None else -1e9))
        return [cand[j] for j in order[:self.p.top_n]]

    def next(self):
        dt = self.datas[0].datetime.date(0)
        key = self._key(dt)
        if key == self._last:
            return
        self._last = key

        M = {}
        for name, d in self._feeds.items():
            if name == "SPY":
                continue
            m = self._metrics(d)
            if m:
                M[name] = m
        if len(M) < 5:
            return

        cons = [t for t, x in M.items() if x["mom"] > 0 and x["close"] > x["s200"]]
        aggr = [t for t, x in M.items() if x["close"] > x["s50"] > x["s200"] and x["high"] >= self.p.high_prox]
        heal = [t for t, x in M.items() if self.sectors.get(t) in HEALTH_SET and x["mom"] > 0]

        picks = set()
        for sleeve in (cons, aggr, heal):
            picks |= set(self._rank(sleeve, M))

        inv = {t: 1.0 / M[t]["vol"] for t in picks if M[t]["vol"] and M[t]["vol"] > 0}
        tot = sum(inv.values())
        weights = {t: inv[t] / tot for t in inv} if tot else {t: 1.0 / len(picks) for t in picks}

        # set every non-benchmark feed to its target (0 = exit), small cash buffer
        for name, d in self._feeds.items():
            if name == "SPY":
                continue
            self.order_target_percent(data=d, target=weights.get(name, 0.0) * 0.98)


# ------------------------------------------------------------------ runner
def run_backtest(price_data, sectors, spy_df=None, rebalance="M", cash=100_000,
                 commission=0.0005, slippage=0.001, sample=False):
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=commission)
    cerebro.broker.set_slippage_perc(perc=slippage)
    for tk, df in price_data.items():
        cerebro.adddata(bt.feeds.PandasData(dataname=df, name=tk))
    if spy_df is not None:
        cerebro.adddata(bt.feeds.PandasData(dataname=spy_df, name="SPY"))
    cerebro.addstrategy(CombinedBook, rebalance=rebalance, sectors=sectors)
    cerebro.addanalyzer(ValueRecorder, _name="val")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="dd")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    strat = cerebro.run()[0]
    rec = strat.analyzers.val.get_analysis()
    dates, equity = rec["dates"], rec["values"]
    if len(equity) < 3:
        raise SystemExit("Not enough bars — need >1y of history before the first rebalance.")

    # benchmark: SPY buy-hold aligned to the recorded dates
    bench = []
    if spy_df is not None:
        spy = spy_df["close"].reindex(pd.to_datetime(dates)).ffill().values
        b0 = next((b for b in spy if b and not np.isnan(b)), None)
        bench = [equity[0] * (b / b0) if b and b0 and not np.isnan(b) else None for b in spy]

    stats = st.summary(equity, n_trials=30)
    # cross-check with backtrader's own analyzers
    bt_sharpe = strat.analyzers.sharpe.get_analysis().get("sharperatio")
    bt_dd = strat.analyzers.dd.get_analysis().get("max", {}).get("drawdown")
    trades = strat.analyzers.trades.get_analysis()
    stats["bt_sharpe"] = round(bt_sharpe, 4) if bt_sharpe else None
    stats["bt_max_drawdown_pct"] = round(bt_dd, 2) if bt_dd else None
    stats["trades"] = trades.get("total", {}).get("closed", 0)
    if bench:
        bser = [b for b in bench if b]
        stats["spy_cagr"] = round(st.cagr(bser) or 0, 4)
        stats["spy_max_drawdown"] = round(st.max_drawdown(bser), 4)

    # downsample and write the dashboard JSON
    step = max(1, len(dates) // 220)
    idx = list(range(0, len(dates), step))
    report = {"date": pd.Timestamp.today().strftime("%Y-%m-%d"), "mode": "combined (backtrader)",
              "engine": "backtrader", "sample": sample, "start": dates[0], "end": dates[-1],
              "config": {"rebalance": rebalance, "cost_bps": int(commission * 1e4),
                         "slip_bps": int(slippage * 1e4), "top_n": TOP_N, "n_trials": 30},
              "dates": [dates[i] for i in idx],
              "equity": [round(equity[i], 2) for i in idx],
              "benchmark": [round(bench[i], 2) if i < len(bench) and bench[i] else None for i in idx],
              "stats": stats}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(report, open(OUT, "w"), separators=(",", ":"))
    print(f"Wrote {OUT}")
    print(f"  combined/backtrader | {dates[0]}..{dates[-1]} | rebalance {rebalance}")
    print(f"  CAGR {stats['cagr']} vs SPY {stats.get('spy_cagr')} | Sharpe {stats['sharpe']} "
          f"(bt {stats['bt_sharpe']}) | maxDD {stats['max_drawdown']} | trades {stats['trades']}")
    print(f"  PSR {stats['psr_vs0']} | Deflated Sharpe {stats['deflated_sharpe']} (N=30)")
    return report


# ------------------------------------------------------------------ data
def _ohlcv(dates, closes, opens):
    idx = pd.to_datetime(dates)
    c = np.array(closes, dtype=float)
    o = np.array(opens, dtype=float)
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.005,
                         "low": np.minimum(o, c) * 0.995, "close": c,
                         "volume": np.full(len(c), 1_000_000)}, index=idx)


def load_yfinance(tickers, start, end):
    import yfinance as yf
    data = yf.download(list(dict.fromkeys(tickers + ["SPY"])), start=start, end=end,
                       interval="1d", auto_adjust=True, progress=False, group_by="ticker")
    idx = data.index
    price_data, spy_df = {}, None
    for t in tickers:
        try:
            sub = data[t][["Open", "High", "Low", "Close", "Volume"]].dropna()
            sub.columns = ["open", "high", "low", "close", "volume"]
            price_data[t] = sub
        except Exception:
            pass
    try:
        s = data["SPY"][["Open", "High", "Low", "Close", "Volume"]].dropna()
        s.columns = ["open", "high", "low", "close", "volume"]
        spy_df = s
    except Exception:
        pass
    return price_data, spy_df


def load_universe_csv(path):
    import csv
    tickers, sectors = [], {}
    with open(path) as f:
        for row in csv.DictReader(f):
            t = (row.get("ticker") or "").strip().upper()
            if t:
                tickers.append(t)
                sectors[t] = (row.get("sector") or "").strip()
    return tickers, sectors


def synthetic():
    rng = np.random.default_rng(11)
    n = 252 * 6
    dates = pd.bdate_range("2018-01-01", periods=n).strftime("%Y-%m-%d").tolist()
    price_data, sectors = {}, {}
    for k in range(36):
        t = f"SYN{k:02d}"
        sectors[t] = "Health Technology" if k % 5 == 0 else f"Sector{k % 6}"
        trend = k < 12
        base, cl, op, drift = 50.0, [], [], 0.0
        for j in range(n):
            if trend and j % 120 == 0:
                drift = rng.uniform(0.0006, 0.0015)
            elif not trend:
                drift = rng.uniform(-0.0003, 0.0004)
            op.append(base)
            base *= 1 + drift + rng.normal(0, 0.016)
            cl.append(base)
        price_data[t] = _ohlcv(dates, cl, op)
    b, bc, bo = 100.0, [], []
    for _ in range(n):
        bo.append(b)
        b *= 1 + 0.0003 + rng.normal(0, 0.009)
        bc.append(b)
    spy_df = _ohlcv(dates, bc, bo)
    return price_data, sectors, spy_df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--universe", default="universe.csv")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--rebalance", choices=["M", "W"], default="M")
    args = ap.parse_args()

    if args.sample:
        price_data, sectors, spy_df = synthetic()
    else:
        from datetime import date
        tickers, sectors = load_universe_csv(args.universe)
        price_data, spy_df = load_yfinance(tickers, args.start, args.end or date.today().isoformat())
    run_backtest(price_data, sectors, spy_df=spy_df, rebalance=args.rebalance, sample=args.sample)


if __name__ == "__main__":
    main()
