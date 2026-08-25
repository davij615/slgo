"""
sensitivity.py — how much do the filter thresholds actually matter?

For each gate in the aggressive screen, this slides that one knob across a grid
(holding the others at baseline) and measures how much the SURVIVOR SET changes:
  • count     — how many names pass
  • jaccard   — overlap with the baseline set (1.0 = identical, 0 = disjoint)
  • retained  — fraction of the baseline names still present

Read it like this: if a knob's jaccard stays high across its whole range, the
exact threshold doesn't matter — the screen is robust to it. If jaccard falls
off a cliff, that knob is load-bearing and a prime overfitting suspect. This
measures SET SENSITIVITY on live data; it is NOT a backtest (we can't get
point-in-time history) and says nothing about returns — only stability.

    python sensitivity.py            # live run -> ../public/sensitivity.json
    python sensitivity.py --sample   # synthetic, for a dashboard demo (no network)
"""
import argparse
import json
import os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "public", "sensitivity.json")

BASELINE = {
    "market_cap_min": 1_000_000_000, "adx_min": 25, "perf_1m_min": 10,
    "perf_3m_min": 20, "min_adv": 20_000_000, "high_proximity": 0.75,
}
GRID = {
    "market_cap_min": [500_000_000, 1_000_000_000, 2_000_000_000, 5_000_000_000],
    "adx_min": [20, 25, 30, 40],
    "perf_1m_min": [5, 10, 15, 20],
    "perf_3m_min": [10, 20, 30, 40],
    "min_adv": [5_000_000, 10_000_000, 20_000_000, 50_000_000],
    "high_proximity": [0.70, 0.75, 0.85, 0.90],
}
LABELS = {
    "market_cap_min": "Market cap floor", "adx_min": "ADX floor",
    "perf_1m_min": "1-month perf floor", "perf_3m_min": "3-month perf floor",
    "min_adv": "Liquidity (ADV) floor", "high_proximity": "52w-high proximity",
}


# ─────────────── pure logic (offline-testable) ───────────────
def jaccard(a, b):
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    u = len(a | b)
    return len(a & b) / u if u else 1.0


def analyze(screen_fn, baseline, grid):
    """screen_fn(params) -> set of survivor tickers. Returns the stability report."""
    base = set(screen_fn(baseline))
    knobs = {}
    for knob, values in grid.items():
        rows = []
        for v in values:
            p = dict(baseline); p[knob] = v
            s = set(screen_fn(p))
            rows.append({
                "value": v, "count": len(s),
                "jaccard": round(jaccard(s, base), 3),
                "retained": round(len(s & base) / max(len(base), 1), 3),
                "baseline": v == baseline[knob],
            })
        # a knob is "fragile" if overlap swings a lot across its range
        js = [r["jaccard"] for r in rows]
        knobs[knob] = {"label": LABELS[knob], "rows": rows,
                       "swing": round(max(js) - min(js), 3)}
    return {"date": date.today().isoformat(), "baseline_count": len(base),
            "baseline": baseline, "knobs": knobs}


# ─────────────── live screen (runs on deploy) ───────────────
def make_screen_fn():
    from tradingview_screener import Query, col

    def screen(p):
        _, df = (Query().set_markets("america")
                 .select("name", "close", "average_volume_30d_calc", "price_52_week_high")
                 .where(
                     col("exchange").isin(["NASDAQ", "NYSE", "AMEX"]),
                     col("close") >= 10,
                     col("market_cap_basic") >= p["market_cap_min"],
                     col("Perf.1M") >= p["perf_1m_min"],
                     col("Perf.3M") >= p["perf_3m_min"],
                     col("Recommend.All") >= 0.1,
                     col("ADX") >= p["adx_min"],
                     col("close") > col("SMA50"),
                     col("SMA50") > col("SMA200"),
                 ).limit(500).get_scanner_data())
        rows = df.to_dict(orient="records")
        return [r["name"] for r in rows
                if (r.get("close") or 0) * (r.get("average_volume_30d_calc") or 0) >= p["min_adv"]
                and (not r.get("price_52_week_high")
                     or (r.get("close") or 0) >= p["high_proximity"] * r["price_52_week_high"])]
    return screen


def sample_screen_fn():
    """Synthetic: most knobs robust, the 1-month-perf floor deliberately fragile."""
    import random
    rng = random.Random(7)
    base = [f"T{i:03d}" for i in range(60)]

    def screen(p):
        keep = set(base)
        # tightening cap/adx/adx trims a few names smoothly (robust)
        keep = set(list(keep)[: 60 - int((p["market_cap_min"] / 1e9) * 2)])
        keep = set(list(keep)[: len(keep) - max(0, (p["adx_min"] - 25) // 5)])
        # 1-month-perf floor is a CLIFF: raising it past baseline guts the set
        if p["perf_1m_min"] > 10:
            keep = set(list(keep)[: max(5, len(keep) - (p["perf_1m_min"] - 10) * 4)])
        return list(keep)
    return screen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args()
    screen_fn = sample_screen_fn() if args.sample else make_screen_fn()
    report = analyze(screen_fn, BASELINE, GRID)
    if args.sample:
        report["sample"] = True
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(report, open(OUT, "w"), separators=(",", ":"))
    print(f"Wrote {OUT}  (baseline survivors: {report['baseline_count']})")
    for k, d in report["knobs"].items():
        flag = "FRAGILE" if d["swing"] > 0.4 else "robust"
        print(f"  {d['label']:22} jaccard swing {d['swing']:.2f}  [{flag}]")


if __name__ == "__main__":
    main()
