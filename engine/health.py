"""
health.py — momentum leaders in the HEALTH universe only.

Covers everything health: pharma, biotech, medical devices/specialties, digital
health, hospitals, health services, and health insurance (managed care) — via
TradingView's two health sectors:

    "Health Technology"  (pharma, biotech, devices, medical specialties)
    "Health Services"    (managed care / insurers, hospitals, health services)

Why this isn't just the aggressive screen with a sector filter:
  • Clinical-stage BIOTECH is unprofitable by design, so the profitability gate
    is OFF by default here (PROFIT_GATE=1 to re-enable for a quality tilt).
  • Health skews smaller/choppier, so cap/price/liquidity floors are lower and
    momentum thresholds a touch looser than the general aggressive book.
  • BINARY EVENT RISK is real: FDA decisions and trial readouts can gap a name
    tens of percent overnight — momentum assumes trends persist; biotech violates
    that violently. This screen ranks leaders; it does NOT neutralize catalyst
    risk. Size down and diversify. (Surfaced in the UI and README too.)

Ranking reuses the shared composite (risk-adjusted 12-1 + 52w-high + sector-
relative). Each name is tagged with its health sub-industry.

    RANK_METHOD=composite python health.py --dry-run
    PROFIT_GATE=1 python health.py --dry-run     # quality tilt (drops pre-revenue biotech)
"""
import argparse
import json
import os
from datetime import date

from tradingview_screener import Query, col
from daily_target import size_equal_weight, diff, render, send_email, PORT_DIR
import signals as sig

TAG = os.environ.get("STRATEGY_TAG", "health")
STATE = os.path.join(PORT_DIR, f"holdings_{TAG}.json")

HEALTH_SECTORS = ["Health Technology", "Health Services"]
ACCOUNT_SIZE = float(os.environ.get("ACCOUNT_SIZE", 10_000))
TOP_N = int(os.environ.get("HEALTH_TOP", 10))
REBALANCE_WEEKDAY = int(os.environ.get("REBALANCE_WEEKDAY", 0))
HOLD_BONUS = float(os.environ.get("HOLD_BONUS", 0.10))
MIN_ADV = float(os.environ.get("MIN_DOLLAR_VOLUME", 3_000_000))
HIGH_PROXIMITY = float(os.environ.get("HIGH_PROXIMITY", 0.70))
RANK_METHOD = os.environ.get("RANK_METHOD", "composite")
PROFIT_GATE = os.environ.get("PROFIT_GATE", "0") == "1"   # OFF: biotech is pre-profit
PRICE_MIN = float(os.environ.get("PRICE_MIN", 5))
CAP_MIN = float(os.environ.get("CAP_MIN", 300_000_000))

COLS = ["name", "description", "close", "Perf.1M", "Perf.3M", "Perf.Y",
        "Volatility.D", "price_52_week_high", "Recommend.All", "ADX",
        "market_cap_basic", "average_volume_30d_calc", "exchange", "sector",
        "industry", "return_on_equity"]


def adv_ok(r):
    return (r.get("close") or 0) * (r.get("average_volume_30d_calc") or 0) >= MIN_ADV


def near_high(r):
    h = r.get("price_52_week_high")
    return h is None or (r.get("close") or 0) >= HIGH_PROXIMITY * h


def profitable(r):
    if not PROFIT_GATE:
        return True
    roe = r.get("roe")
    return roe is None or roe > 0


def normalize(r):
    return {
        "ticker": r["name"], "symbol": r.get("ticker", r["name"]),
        "company": r.get("description", ""), "close": r.get("close"),
        "perf_1m": r.get("Perf.1M"), "perf_3m": r.get("Perf.3M"),
        "perf_y": r.get("Perf.Y"), "vol": r.get("Volatility.D"),
        "high_52w": r.get("price_52_week_high"), "sector": r.get("sector"),
        "industry": r.get("industry"), "roe": r.get("return_on_equity"),
        "adx": r.get("ADX"), "mom121": sig.mom_12_1(r.get("Perf.Y"), r.get("Perf.1M")),
    }


def score_pool(rows, method):
    if method == "composite":
        for r, s in zip(rows, sig.composite_scores(rows)):
            r["score"] = s
    else:
        for r in rows:
            r["score"] = sig.score_one(method, r)
    return rows


def select_top_n(pool, held, n, bonus):
    return sorted(pool, key=lambda r: -((r.get("score") or -1e9) * (1 + bonus)
                                        if r["ticker"] in held else (r.get("score") or -1e9)))[:n]


def build_entry():
    return (Query().set_markets("america").select(*COLS).where(
        col("sector").isin(HEALTH_SECTORS),
        col("exchange").isin(["NASDAQ", "NYSE", "AMEX"]),
        col("close") >= PRICE_MIN,
        col("market_cap_basic") >= CAP_MIN,
        col("Perf.1M") >= 10,
        col("Perf.3M") >= 15,
        col("Recommend.All") >= -0.1,
        col("ADX") >= 20,
        col("close") > col("SMA50"),
        col("SMA50") > col("SMA200"),
    ).order_by("Perf.3M", ascending=False).limit(150))


def build_hold(symbols):
    return (Query().set_markets("america").set_tickers(*symbols).select(*COLS)
            .where(col("close") > col("SMA50"),
                   col("Recommend.All") >= -0.3,
                   col("Perf.1M") > -20))


def fetch_entrants():
    _, df = build_entry().get_scanner_data()
    rows = [r for r in df.to_dict(orient="records") if adv_ok(r) and near_high(r)]
    return [r for r in (normalize(x) for x in rows) if profitable(r)]


def fetch_hold(symbols):
    if not symbols:
        return [], {}
    _, df = build_hold(symbols).get_scanner_data()
    rows = [r for r in df.to_dict(orient="records") if adv_ok(r)]
    return [normalize(r) for r in rows], {r["name"]: r.get("close") for r in rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    today = date.today()
    asof = today.isoformat()

    state = json.load(open(STATE)) if os.path.exists(STATE) else {"last_rebalance": None, "positions": {}}
    positions = state.get("positions", {})
    current_shares = {t: p.get("shares", 0) for t, p in positions.items()}
    held_symbols = [p.get("symbol", t) for t, p in positions.items()]

    last = date.fromisoformat(state["last_rebalance"]) if state.get("last_rebalance") else None
    is_rebal = args.force or last is None or today.weekday() == REBALANCE_WEEKDAY or \
        (last and (today - last).days >= 7)
    if not is_rebal:
        print(f"Not a rebalance day. Holding {len(positions)} health names.")
        return

    entrants = fetch_entrants()
    held_rows, hold_prices = fetch_hold(held_symbols)
    held_ok = {r["ticker"] for r in held_rows}

    pool = {r["ticker"]: r for r in entrants}
    for r in held_rows:
        pool.setdefault(r["ticker"], r)
    pool = list(pool.values())

    score_pool(pool, RANK_METHOD)
    target_rows = select_top_n(pool, held_ok, TOP_N, HOLD_BONUS)

    names = [t["ticker"] for t in target_rows]
    price_map = {t["ticker"]: t["close"] for t in target_rows}
    price_map.update({k: v for k, v in hold_prices.items() if v})
    for t, p in positions.items():
        price_map.setdefault(t, p.get("price"))

    target_shares, cash = size_equal_weight(names, price_map, ACCOUNT_SIZE)

    log = []
    for t in names:
        if t not in current_shares:
            log.append(("ENTER", t, f"health {RANK_METHOD} top-{TOP_N}"))
    for t in current_shares:
        if t not in names:
            log.append(("EXIT", t, "broke hold test" if t not in held_ok else f"fell below top {TOP_N}"))

    orders = diff(target_shares, current_shares, price_map)
    sheet = render(orders, cash, asof, is_rebal, log).replace(
        "TARGET SHEET", f"HEALTH [{RANK_METHOD}] TOP-{TOP_N}")
    print("\n" + sheet + "\n")

    new_positions = {t: {"shares": target_shares.get(t, 0),
                         "symbol": next((e["symbol"] for e in target_rows if e["ticker"] == t), t),
                         "price": price_map.get(t)} for t in names}
    os.makedirs(PORT_DIR, exist_ok=True)
    pub = {"date": asof, "strategy": f"{TAG}-{RANK_METHOD}-top{TOP_N}", "account": ACCOUNT_SIZE,
           "cash": cash, "orders": orders, "positions": {t: new_positions[t]["shares"] for t in names},
           "picks": [{"ticker": t["ticker"], "company": t["company"], "industry": t.get("industry"),
                      "score": round(t.get("score") or 0, 3), "mom121": round(t.get("mom121") or 0, 3)}
                     for t in target_rows]}
    json.dump(pub, open(os.path.join(PORT_DIR, f"latest_{TAG}.json"), "w"))

    send_email(f"{TAG} [{RANK_METHOD}] {asof}: {len([o for o in orders if o['action'] != 'HOLD'])} orders", sheet)

    if not args.dry_run:
        json.dump({"last_rebalance": asof, "positions": new_positions}, open(STATE, "w"))
        print("State updated (health).")
    else:
        print("Dry run — state unchanged.")


if __name__ == "__main__":
    main()
