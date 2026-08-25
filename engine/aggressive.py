"""
aggressive.py — the CHALLENGER, upgraded with research-backed momentum signals.

Screen (eligibility, whole listed US market, no OTC): price >= $10, cap >= $1B,
ADV >= $20M, uptrend stack (close > SMA50 > SMA200), within 25% of 52-week high,
Perf 1M >= 10%, Perf 3M >= 20%, ADX >= 25, tech rating Buy+, and (optional) a
profitability gate (ROE > 0) to avoid junk rallies.

RANKING (this is the upgrade) — pick via RANK_METHOD:
  raw        old (Perf.1M + Perf.3M)               — for racing/baseline
  mom121     12-1 momentum, skips the recent month — Jegadeesh & Titman
  riskadj    12-1 / volatility                     — Barroso & Santa-Clara
  composite  z-blend of risk-adj 12-1, 52w-high,   — DEFAULT, strongest evidence
             and sector-relative 12-1              (George&Hwang, Moskowitz&Grinblatt)

Optional second stage: FIP_ENABLED=1 applies Frog-in-the-Pan smoothness
(Da/Gurun/Warachka) to the top pool using daily bars (needs yfinance) and keeps
the smoothest names. Earnings-revision momentum is a documented hook (needs a
paid estimates feed) — see fetch_earnings_revision().

    RANK_METHOD=composite python aggressive.py --dry-run
    RANK_METHOD=raw STRATEGY_TAG=baseline python aggressive.py --dry-run   # race a variant

Env: ACCOUNT_SIZE, AGGR_TOP (5), REBALANCE_WEEKDAY, HOLD_BONUS (0.10),
MIN_DOLLAR_VOLUME (20M), HIGH_PROXIMITY (0.75), RANK_METHOD (composite),
PROFIT_GATE (1), FIP_ENABLED (0), FIP_POOL (20), STRATEGY_TAG, SMTP_* for email.
Places NO orders.
"""
import argparse
import json
import os
from datetime import date

from tradingview_screener import Query, col
from daily_target import size_equal_weight, diff, render, send_email, PORT_DIR
import signals as sig

TAG = os.environ.get("STRATEGY_TAG", "aggressive")
STATE = os.path.join(PORT_DIR, f"holdings_{TAG}.json")

ACCOUNT_SIZE = float(os.environ.get("ACCOUNT_SIZE", 10_000))
TOP_N = int(os.environ.get("AGGR_TOP", 5))
REBALANCE_WEEKDAY = int(os.environ.get("REBALANCE_WEEKDAY", 0))
HOLD_BONUS = float(os.environ.get("HOLD_BONUS", 0.10))
MIN_ADV = float(os.environ.get("MIN_DOLLAR_VOLUME", 20_000_000))
HIGH_PROXIMITY = float(os.environ.get("HIGH_PROXIMITY", 0.75))
RANK_METHOD = os.environ.get("RANK_METHOD", "composite")
PROFIT_GATE = os.environ.get("PROFIT_GATE", "1") == "1"
FIP_ENABLED = os.environ.get("FIP_ENABLED", "0") == "1"
FIP_POOL = int(os.environ.get("FIP_POOL", 20))

SCORE_COLS = ["name", "description", "close", "Perf.1M", "Perf.3M", "Perf.Y",
              "Volatility.D", "price_52_week_high", "Recommend.All", "ADX",
              "market_cap_basic", "average_volume_30d_calc", "exchange",
              "sector", "return_on_equity"]


# ─────────────── pure helpers (offline-testable) ───────────────
def adv_ok(r):
    return (r.get("close") or 0) * (r.get("average_volume_30d_calc") or 0) >= MIN_ADV


def near_high(r):
    h = r.get("price_52_week_high")
    return h is None or (r.get("close") or 0) >= HIGH_PROXIMITY * h


def profitable(r):
    if not PROFIT_GATE:
        return True
    roe = r.get("roe")                     # normalized key (TV return_on_equity)
    return roe is None or roe > 0          # null-tolerant; drop only clear losers


def normalize(r):
    """TradingView row -> scoring dict with mom121 computed."""
    return {
        "ticker": r["name"], "symbol": r.get("ticker", r["name"]),
        "company": r.get("description", ""), "close": r.get("close"),
        "perf_1m": r.get("Perf.1M"), "perf_3m": r.get("Perf.3M"),
        "perf_y": r.get("Perf.Y"), "vol": r.get("Volatility.D"),
        "high_52w": r.get("price_52_week_high"), "sector": r.get("sector"),
        "roe": r.get("return_on_equity"), "adx": r.get("ADX"),
        "mom121": sig.mom_12_1(r.get("Perf.Y"), r.get("Perf.1M")),
    }


def score_pool(rows, method):
    """Attach a 'score' to every row in the cross-section."""
    if method == "composite":
        for r, sc in zip(rows, sig.composite_scores(rows)):
            r["score"] = sc
    else:
        for r in rows:
            r["score"] = sig.score_one(method, r)
    return rows


def select_top_n(pool, held_set, n, bonus):
    """Rank by score; incumbents get a loyalty bonus to limit churn."""
    for r in pool:
        if r["ticker"] in held_set and r.get("score") is not None:
            r = r  # bonus applied below
    ranked = sorted(
        pool,
        key=lambda r: -((r.get("score") or -1e9) * (1 + bonus) if r["ticker"] in held_set
                         else (r.get("score") or -1e9)))
    return ranked[:n]


# ─────────────── Frog-in-the-Pan second stage (needs daily bars) ───────────────
def apply_fip(pool, n):
    """Keep the smoothest of the top FIP_POOL by composite (QMOM-style)."""
    try:
        import yfinance as yf
        import pandas as pd
    except Exception:
        print("(FIP skipped — yfinance not installed)")
        return pool[:n]
    candidates = pool[:max(FIP_POOL, n)]
    syms = [c["symbol"].split(":")[-1] for c in candidates]
    try:
        data = yf.download(syms, period="1y", interval="1d",
                           auto_adjust=True, progress=False, group_by="ticker")
    except Exception as e:
        print(f"(FIP skipped — download failed: {e})")
        return pool[:n]
    for c in candidates:
        sym = c["symbol"].split(":")[-1]
        try:
            close = data[sym]["Close"].dropna()
            rets = close.pct_change().dropna().tolist()
            c["fip"] = sig.information_discreteness(rets)
        except Exception:
            c["fip"] = None
    # smoothest first (most negative ID); names with no FIP fall to the back
    candidates.sort(key=lambda c: (c.get("fip") if c.get("fip") is not None else 1e9))
    return candidates[:n]


def fetch_earnings_revision(symbols):
    """HOOK (not implemented): earnings-estimate-revision / SUE momentum.
    Strong, orthogonal evidence (PEAD; Chan-Jegadeesh-Lakonishok) but needs an
    analyst-estimates feed (I/B/E/S, Zacks, FactSet). Wire your feed here to
    return {ticker: revision_score} and blend it into the composite."""
    return {}


# ─────────────── live data ───────────────
def build_entry():
    return (Query().set_markets("america").select(*SCORE_COLS).where(
        col("exchange").isin(["NASDAQ", "NYSE", "AMEX"]),
        col("close") >= 10,
        col("market_cap_basic") >= 1_000_000_000,
        col("Perf.1M") >= 10,
        col("Perf.3M") >= 20,
        col("Recommend.All") >= 0.1,
        col("ADX") >= 25,
        col("close") > col("SMA50"),
        col("SMA50") > col("SMA200"),
    ).order_by("Perf.3M", ascending=False).limit(150))


def build_hold(symbols):
    return (Query().set_markets("america").set_tickers(*symbols).select(*SCORE_COLS)
            .where(col("close") > col("SMA50"),
                   col("Recommend.All") >= -0.1,
                   col("Perf.1M") > -15))


def fetch_entrants():
    _, df = build_entry().get_scanner_data()
    rows = [r for r in df.to_dict(orient="records") if adv_ok(r) and near_high(r)]
    out = [normalize(r) for r in rows]
    return [r for r in out if profitable(r)]


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
        print(f"Not a rebalance day. Holding {len(positions)} names ({TAG}).")
        return

    entrants = fetch_entrants()
    held_rows, hold_prices = fetch_hold(held_symbols)
    held_ok = {r["ticker"] for r in held_rows}

    # combined cross-section (entrants + still-OK holders), dedup by ticker
    pool = {r["ticker"]: r for r in entrants}
    for r in held_rows:
        pool.setdefault(r["ticker"], r)
    pool = list(pool.values())

    score_pool(pool, RANK_METHOD)
    target_rows = apply_fip(sorted(pool, key=lambda r: -(r.get("score") or -1e9)), TOP_N) \
        if FIP_ENABLED else select_top_n(pool, held_ok, TOP_N, HOLD_BONUS)

    names = [t["ticker"] for t in target_rows]
    price_map = {t["ticker"]: t["close"] for t in target_rows}
    price_map.update({k: v for k, v in hold_prices.items() if v})
    for t, p in positions.items():
        price_map.setdefault(t, p.get("price"))

    target_shares, cash = size_equal_weight(names, price_map, ACCOUNT_SIZE)

    log = []
    for t in names:
        if t not in current_shares:
            log.append(("ENTER", t, f"{RANK_METHOD} top-{TOP_N}"))
    for t in current_shares:
        if t not in names:
            log.append(("EXIT", t, "broke hold test" if t not in held_ok else f"fell below top {TOP_N}"))

    orders = diff(target_shares, current_shares, price_map)
    sheet = render(orders, cash, asof, is_rebal, log).replace(
        "TARGET SHEET", f"{TAG.upper()} [{RANK_METHOD}] TOP-{TOP_N}")
    print("\n" + sheet + "\n")

    new_positions = {t: {"shares": target_shares.get(t, 0),
                         "symbol": next((e["symbol"] for e in target_rows if e["ticker"] == t), t),
                         "price": price_map.get(t)} for t in names}
    os.makedirs(PORT_DIR, exist_ok=True)
    pub = {"date": asof, "strategy": f"{TAG}-{RANK_METHOD}-top{TOP_N}", "account": ACCOUNT_SIZE,
           "cash": cash, "orders": orders, "positions": {t: new_positions[t]["shares"] for t in names},
           "picks": [{"ticker": t["ticker"], "company": t["company"], "score": round(t.get("score") or 0, 3),
                      "mom121": round(t.get("mom121") or 0, 3), "fip": t.get("fip")} for t in target_rows]}
    json.dump(pub, open(os.path.join(PORT_DIR, f"{TAG}-{asof}.json"), "w"))
    json.dump(pub, open(os.path.join(PORT_DIR, f"latest_{TAG}.json"), "w"))

    n_act = len([o for o in orders if o["action"] != "HOLD"])
    send_email(f"{TAG} [{RANK_METHOD}] {asof}: {n_act} orders", sheet)

    if not args.dry_run:
        json.dump({"last_rebalance": asof, "positions": new_positions}, open(STATE, "w"))
        print(f"State updated ({TAG}).")
    else:
        print("Dry run — state unchanged.")


if __name__ == "__main__":
    main()
