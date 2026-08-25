"""
momentum_age.py — how long has each name actually been trending?

Two complementary reads of "how long it's had momentum":

  • TREND AGE (from price, available now): consecutive trading days the stock has
    closed above its 50- and 200-day moving averages, plus the share of the last
    ~6 months spent above the 50-day. A name above its 200-day for 250 days has
    run for a year; one above its 50-day for 8 days just turned up.

  • SCREEN TENURE (from our own snapshot log, accrues over time): how many
    consecutive snapshot runs it has held its place in the screen (snapshot.py).

Long trend age is informative, not a buy or sell signal — the momentum literature
warns that very extended moves are also more reversal-prone, so this flags
late-stage names rather than endorsing them.

    python momentum_age.py            # live -> ../public/momentum_age.json (needs yfinance)
    python momentum_age.py --sample   # synthetic demo, no network
"""
import argparse
import json
import os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "public", "momentum_age.json")
SNAP_DIR = os.path.join(HERE, "..", "public", "snapshots")
EXTENDED_DAYS = int(os.environ.get("EXTENDED_DAYS", 250))   # late-stage flag


# ─────────────── pure trend-age math (offline-testable) ───────────────
def sma_series(closes, w):
    out = []
    for i in range(len(closes)):
        out.append(sum(closes[i + 1 - w:i + 1]) / w if i + 1 >= w else None)
    return out


def days_above_sma(closes, w):
    """Consecutive days (ending today) the close has stayed at/above its w-day SMA."""
    s = sma_series(closes, w)
    streak = 0
    for i in range(len(closes) - 1, -1, -1):
        if s[i] is None or closes[i] < s[i]:
            break
        streak += 1
    return streak


def frac_above_sma(closes, w, lookback=126):
    """Share of the last `lookback` days spent above the w-day SMA (trend quality)."""
    s = sma_series(closes, w)
    pairs = [(closes[i], s[i]) for i in range(len(closes)) if s[i] is not None][-lookback:]
    if not pairs:
        return None
    return round(sum(1 for c, m in pairs if c >= m) / len(pairs), 3)


def trend_age(closes):
    return {
        "above50": days_above_sma(closes, 50),
        "above200": days_above_sma(closes, 200),
        "frac50_6m": frac_above_sma(closes, 50, 126),
        "extended": days_above_sma(closes, 50) >= EXTENDED_DAYS,
    }


# ─────────────── live build ───────────────
def load_tenure():
    p = os.path.join(SNAP_DIR, "tenure.json")
    return json.load(open(p)) if os.path.exists(p) else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args()
    rows = sample_rows() if args.sample else live_rows()
    report = {"date": date.today().isoformat(), "count": len(rows), "rows": rows}
    if args.sample:
        report["sample"] = True
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(report, open(OUT, "w"), separators=(",", ":"))
    print(f"Wrote {OUT} ({len(rows)} names)")


def live_rows():
    import yfinance as yf
    from snapshot import build_query, liquid
    _, df = build_query().get_scanner_data()
    survivors = liquid(df.to_dict(orient="records"))
    tenure = load_tenure()
    syms = [r.get("ticker", r["name"]).split(":")[-1] for r in survivors]
    data = yf.download(syms, period="2y", interval="1d", auto_adjust=True,
                       progress=False, group_by="ticker")
    out = []
    for r in survivors:
        tk = r["name"]
        sym = r.get("ticker", tk).split(":")[-1]
        try:
            closes = data[sym]["Close"].dropna().tolist()
            age = trend_age(closes)
        except Exception:
            age = {"above50": None, "above200": None, "frac50_6m": None, "extended": False}
        out.append({"ticker": tk, "company": r.get("description", ""),
                    "sector": r.get("sector"), "close": r.get("close"),
                    "streak": tenure.get(tk, {}).get("streak", 0),
                    "first_seen": tenure.get(tk, {}).get("first_seen"), **age})
    out.sort(key=lambda x: (-(x["above200"] or 0), -(x["above50"] or 0)))
    return out


def sample_rows():
    """Illustrative spread: fresh breakouts -> mid-trend -> extended runners."""
    rows = [
        ("RUN", "Long Runner", "Technology", 287, 410, 0.98, 58),
        ("LATE", "Late Stage", "Energy", 262, 355, 0.91, 31),
        ("STDY", "Steady Climb", "Industrials", 132, 210, 0.95, 22),
        ("NVDA", "Anchor Co", "Technology", 95, 180, 0.97, 40),
        ("CHOP", "Choppy Mover", "Consumer", 8, 60, 0.62, 6),
        ("FRSH", "Fresh Breakout", "Healthcare", 5, 12, 0.55, 3),
    ]
    out = [{"ticker": tk, "company": co, "sector": sec, "close": 100.0,
            "streak": streak, "first_seen": "2026-04-15",
            "above50": a50, "above200": a200, "frac50_6m": frac,
            "extended": a50 >= EXTENDED_DAYS} for tk, co, sec, a50, a200, frac, streak in rows]
    out.sort(key=lambda x: -x["above200"])
    return out


if __name__ == "__main__":
    main()
