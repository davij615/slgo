"""
daily_target.py — Rung 1 + turnover-reduction layer.

Pipeline each run:
  1. fetch STRICT entry survivors (liquidity-filtered)        -> candidates to add
  2. fetch LOOSE hold status for current holdings             -> who's still OK to hold
  3. portfolio.decide(): weekly rebalance + exit hysteresis   -> target names + state
  4. size equal-weight on rebalance days; otherwise hold      -> share targets
  5. diff vs current shares -> BUY/SELL/HOLD sheet -> print/save/email
Places NO orders. After a real run it records holdings + hysteresis state so the
next day's decision is correct. Use --dry-run to preview without changing state.

Env: ACCOUNT_SIZE, MAX_POSITIONS, REBALANCE_WEEKDAY (0=Mon), EXIT_GRACE_DAYS,
MIN_DOLLAR_VOLUME, HOLD_CHG_FLOOR, and SMTP_* / EMAIL_* for opt-in email.
"""
import argparse
import json
import math
import os
import smtplib
from datetime import date
from email.message import EmailMessage

import portfolio as pf
from snapshot import build_query, build_hold_query, liquid
import signals as sig

HERE = os.path.dirname(os.path.abspath(__file__))
PORT_DIR = os.path.join(HERE, "..", "public", "portfolio")
STATE = os.path.join(PORT_DIR, "holdings.json")

ACCOUNT_SIZE = float(os.environ.get("ACCOUNT_SIZE", 10_000))
RANK_METHOD = os.environ.get("RANK_METHOD", "composite")   # composite|mom121|riskadj|chg
CFG = {
    "MAX_POSITIONS": int(os.environ.get("MAX_POSITIONS", 20)),   # top 5 / 10 / 20
    "REBALANCE_WEEKDAY": int(os.environ.get("REBALANCE_WEEKDAY", 0)),
    "EXIT_GRACE_DAYS": int(os.environ.get("EXIT_GRACE_DAYS", 3)),
}


def _rank_entrants(rows):
    """Score conservative survivors by RANK_METHOD so the engine fills slots with
    the best names, not just the highest 1-month change (reversal-prone)."""
    sd = [{"name": r["name"], "symbol": r.get("ticker", r["name"]),
           "close": r.get("close"), "company": r.get("description", ""),
           "chg1m": r.get("change|1M"), "vol": r.get("Volatility.D"),
           "high_52w": r.get("price_52_week_high"), "sector": r.get("sector"),
           "mom121": sig.mom_12_1(r.get("Perf.Y"), r.get("change|1M"))} for r in rows]
    if RANK_METHOD == "composite":
        for r, s in zip(sd, sig.composite_scores(sd)):
            r["score"] = s
    elif RANK_METHOD == "mom121":
        for r in sd:
            r["score"] = r["mom121"]
    elif RANK_METHOD == "riskadj":
        for r in sd:
            r["score"] = sig.risk_adjusted(r["mom121"], r["vol"])
    else:  # "chg" — original 1-month-change order
        for r in sd:
            r["score"] = r["chg1m"]
    sd.sort(key=lambda r: -(r["score"] if r["score"] is not None else -1e9))
    return sd


def fetch_entry():
    _, df = build_query().get_scanner_data()
    rows = liquid(df.to_dict(orient="records"))
    return [{"ticker": r["name"], "symbol": r["symbol"], "price": r["close"],
             "score": r["score"], "company": r["company"]} for r in _rank_entrants(rows)]


def fetch_hold_ok(symbols):
    """Tickers still passing the loose hold test (and still liquid)."""
    if not symbols:
        return set(), {}
    _, df = build_hold_query(symbols).get_scanner_data()
    rows = liquid(df.to_dict(orient="records"))
    ok = {r["name"] for r in rows}
    prices = {r["name"]: r.get("close") for r in rows}
    return ok, prices


def size_equal_weight(names, price_map, account):
    n = len(names)
    if n == 0:
        return {}, account
    each = account / n
    shares, deployed = {}, 0.0
    for t in names:
        px = price_map.get(t) or 0
        s = math.floor(each / px) if px > 0 else 0
        shares[t] = s
        deployed += s * px
    return shares, round(account - deployed, 2)


def diff(target_shares, current_shares, price_map):
    orders, names = [], set(target_shares) | set(current_shares)
    for t in sorted(names):
        have, want = current_shares.get(t, 0), target_shares.get(t, 0)
        px = price_map.get(t)
        if want > have:
            orders.append({"action": "BUY", "ticker": t, "shares": want - have, "price": px})
        elif want < have:
            orders.append({"action": "SELL", "ticker": t, "shares": have - want, "price": px})
        else:
            orders.append({"action": "HOLD", "ticker": t, "shares": have, "price": px})
    rank = {"SELL": 0, "BUY": 1, "HOLD": 2}
    return sorted(orders, key=lambda o: (rank[o["action"]], o["ticker"]))


def render(orders, cash, asof, is_rebal, log):
    acted = [o for o in orders if o["action"] != "HOLD"]
    holds = [o for o in orders if o["action"] == "HOLD"]
    lines = [f"TARGET SHEET — {asof}  [{'REBALANCE' if is_rebal else 'hold day'}]",
             f"Account ${ACCOUNT_SIZE:,.0f} · ~${cash:,.0f} cash · "
             f"weekly rebalance, {CFG['EXIT_GRACE_DAYS']}-day exit grace",
             "=" * 56, "", "ORDERS (you place these):"]
    if not acted:
        lines.append("  (no changes — hold everything)")
    for o in acted:
        px = f"@ ~${o['price']:.2f}" if o["price"] else ""
        lines.append(f"  {o['action']:<4} {o['shares']:>5} {o['ticker']:<6} {px}")
    if holds:
        lines += ["", "HOLDING: " + ", ".join(f"{o['ticker']}({o['shares']})" for o in holds)]
    why = [f"  {a} {t} — {r}" for a, t, r in log]
    if why:
        lines += ["", "WHY:"] + why
    lines += ["", "-" * 56, "No orders placed. Not advice. Verify before trading."]
    return "\n".join(lines)


def send_email(subject, body):
    need = ["SMTP_HOST", "SMTP_USER", "SMTP_PASS", "EMAIL_FROM", "EMAIL_TO"]
    if not all(os.environ.get(k) for k in need):
        print("(email skipped — SMTP env vars not set)")
        return
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, os.environ["EMAIL_FROM"], os.environ["EMAIL_TO"]
    msg.set_content(body)
    with smtplib.SMTP_SSL(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", 465))) as s:
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        s.send_message(msg)
    print(f"(emailed to {os.environ['EMAIL_TO']})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    today = date.today()
    asof = today.isoformat()

    state = json.load(open(STATE)) if os.path.exists(STATE) else {"last_rebalance": None, "positions": {}}
    positions = state.get("positions", {})
    current_shares = {t: p.get("shares", 0) for t, p in positions.items()}
    held_symbols = [p.get("symbol", t) for t, p in positions.items()]

    entry = fetch_entry()
    hold_ok, hold_prices = fetch_hold_ok(held_symbols)

    target_names, new_state, log, is_rebal = pf.decide(today, entry, hold_ok, state, CFG)

    # price map: entrants (current) + hold-query prices + last known
    price_map = {e["ticker"]: e["price"] for e in entry}
    price_map.update({k: v for k, v in hold_prices.items() if v})
    for t, p in positions.items():
        price_map.setdefault(t, p.get("price"))

    if is_rebal:
        target_shares, cash = size_equal_weight(target_names, price_map, ACCOUNT_SIZE)
    else:
        # hold day: keep current shares for survivors; exited names fall to 0 (sold)
        target_shares = {t: current_shares.get(t, 0) for t in target_names}
        spent = sum(s * (price_map.get(t) or 0) for t, s in target_shares.items())
        cash = round(ACCOUNT_SIZE - spent, 2)

    orders = diff(target_shares, current_shares, price_map)
    sheet = render(orders, cash, asof, is_rebal, log)
    print("\n" + sheet + "\n")

    # persist outputs + carry hysteresis state (days_out/entered) forward with new shares
    for t in new_state["positions"]:
        new_state["positions"][t]["shares"] = target_shares.get(t, 0)
        new_state["positions"][t].setdefault("symbol", price_map and
                                             next((e["symbol"] for e in entry if e["ticker"] == t), t))
        new_state["positions"][t]["price"] = price_map.get(t)
    os.makedirs(PORT_DIR, exist_ok=True)
    pub = {"date": asof, "account": ACCOUNT_SIZE, "cash": cash, "rebalance": is_rebal,
           "orders": orders, "positions": {t: new_state["positions"][t]["shares"] for t in new_state["positions"]}}
    json.dump(pub, open(os.path.join(PORT_DIR, f"target-{asof}.json"), "w"))
    json.dump(pub, open(os.path.join(PORT_DIR, "latest.json"), "w"))

    n_act = len([o for o in orders if o["action"] != "HOLD"])
    send_email(f"Target {asof}: {n_act} orders, {len(target_names)} positions", sheet)

    if not args.dry_run:
        json.dump(new_state, open(STATE, "w"))
        print("State updated (assumes the sheet was executed).")
    else:
        print("Dry run — state unchanged.")


if __name__ == "__main__":
    main()
