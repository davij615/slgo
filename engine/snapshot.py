"""
snapshot.py — the screen queries (one source of truth) + daily survivor logging.

Defines the STRICT entry screen and the LOOSE hold screen used by the
turnover-reduction layer, plus the liquidity filter. snapshot's own job is to
record each day's strict survivors to public/snapshots/ for a forward record.
"""
import json
import os
from datetime import date
from tradingview_screener import Query, col

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(HERE, "..", "public", "snapshots")

# Liquidity: require this much average daily DOLLAR volume so orders are fillable.
MIN_DOLLAR_VOLUME = float(os.environ.get("MIN_DOLLAR_VOLUME", 5_000_000))
HOLD_CHG_FLOOR = float(os.environ.get("HOLD_CHG_FLOOR", 0.0))  # exit margin

COLUMNS = ["name", "description", "close", "market_cap_basic", "change|1M",
           "Perf.W", "Perf.Y", "ADX", "Volatility.D", "Recommend.All|1M",
           "recommendation_mark", "sector", "average_volume_30d_calc",
           "price_52_week_high"]


def build_query():
    """STRICT entry screen — the picture, whole US market."""
    return (Query().set_markets("america").select(*COLUMNS).where(
        col("market_cap_basic") >= 500_000_000,
        col("change|1M") >= 5,
        col("Perf.W") > 0,
        col("ADX") > 40,
        col("Volatility.D") < 5,
        col("recommendation_mark").between(1, 2.5),
        col("Recommend.All|1M").between(-0.1, 1),
        col("Recommend.MA|1M").between(-0.1, 1),
        col("Recommend.Other|1M").between(-0.1, 1),
    ).order_by("change|1M", ascending=False).limit(300))


def build_hold_query(symbols):
    """LOOSE hold screen for specific held tickers: still mid-cap and still
    trending up by a margin (chg_1m > floor). Failing this starts the exit clock."""
    return (Query().set_markets("america").set_tickers(*symbols)
            .select("name", "close", "change|1M", "market_cap_basic",
                    "average_volume_30d_calc")
            .where(col("market_cap_basic") >= 500_000_000,
                   col("change|1M") > HOLD_CHG_FLOOR))


def liquid(rows):
    """Keep rows whose avg daily dollar volume clears the liquidity floor."""
    out = []
    for r in rows:
        px = r.get("close") or 0
        vol = r.get("average_volume_30d_calc") or 0
        if px * vol >= MIN_DOLLAR_VOLUME:
            out.append(r)
    return out


def update_tenure(prev, tickers, today):
    """Maintain a per-ticker streak of how many consecutive snapshot runs a name
    has stayed in the screen. prev: {ticker: record}. Returns the updated map.
    streak = consecutive runs present now; total_days = lifetime appearances;
    first_seen preserved across exits so returning names keep their history."""
    cur = set(tickers)
    out = {}
    for t in cur:
        r = prev.get(t, {})
        streak = r.get("streak", 0) + 1 if r.get("present") else 1
        out[t] = {"first_seen": r.get("first_seen", today), "last_seen": today,
                  "streak": streak, "total_days": r.get("total_days", 0) + 1,
                  "present": True}
    for t, r in prev.items():               # carry exited names (streak resets, history kept)
        if t not in cur:
            out[t] = {**r, "present": False, "streak": 0}
    return out


def main():
    _, df = build_query().get_scanner_data()
    rows = liquid(df.to_dict(orient="records"))
    today = date.today().isoformat()
    os.makedirs(SNAP_DIR, exist_ok=True)
    with open(os.path.join(SNAP_DIR, f"{today}.json"), "w") as f:
        json.dump({"date": today, "count": len(rows), "rows": rows},
                  f, separators=(",", ":"))
    idx_path = os.path.join(SNAP_DIR, "index.json")
    idx = json.load(open(idx_path)) if os.path.exists(idx_path) else []
    idx = [e for e in idx if e["date"] != today]
    idx.insert(0, {"date": today, "count": len(rows)})
    json.dump(idx, open(idx_path, "w"), separators=(",", ":"))

    # tenure: how long each name has held its place in the screen
    ten_path = os.path.join(SNAP_DIR, "tenure.json")
    prev = json.load(open(ten_path)) if os.path.exists(ten_path) else {}
    tenure = update_tenure(prev, [r["name"] for r in rows], today)
    json.dump(tenure, open(ten_path, "w"), separators=(",", ":"))

    longest = sorted([t for t in tenure.values() if t["present"]],
                     key=lambda x: -x["streak"])[:3]
    streaks = ", ".join(f"{s['streak']}d" for s in longest) or "—"
    print(f"{today}: {len(rows)} survivors recorded; longest streaks: {streaks}")


if __name__ == "__main__":
    main()
