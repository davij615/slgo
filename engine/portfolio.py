"""
portfolio.py — the turnover-reduction layer (pure logic, fully testable offline).

Three ideas, all aimed at trading less without giving up the signal:

1. WEEKLY REBALANCE — new positions are only added on one weekday (or if a week
   has lapsed). Between rebalances the book is left alone. Cuts the daily churn
   where you buy a name and sell it the next day on noise.

2. EXIT HYSTERESIS (dual threshold + grace) — you ENTER on the strict screen
   (chg_1m > 5%, all the rating/ADX/vol rules), but you only EXIT when a name
   fails a LOOSER "still OK to hold" test (chg_1m <= HOLD_CHG_FLOOR), and even
   then only after it has failed for EXIT_GRACE_DAYS in a row. So a one-day dip
   doesn't knock a name out — it has to genuinely deteriorate.

3. NO FORCED ROTATION — a full book doesn't kick out a holder just because a
   hotter name appeared. Holders leave only via the exit rule. Empty slots get
   filled by the best available entrants. (Rotation is pure turnover.)

The liquidity filter lives in the screen query, not here (see screen.js / the
Python fetchers) — it just shrinks the candidate set to tradeable names.

`decide()` is pure: feed it today's survivors + state, get back the target names
and new state. The data fetching that produces its inputs is in daily_target.py.
"""
from __future__ import annotations
from datetime import date, timedelta

DEFAULTS = {
    "REBALANCE_WEEKDAY": 0,    # 0 = Monday
    "EXIT_GRACE_DAYS": 3,      # consecutive days failing the hold test before exit
    "MAX_POSITIONS": 20,
}


def _as_date(d):
    if isinstance(d, date):
        return d
    return date.fromisoformat(d) if d else None


def decide(today, entry_survivors, hold_ok, state, cfg=None):
    """
    today           : date
    entry_survivors : list of dicts passing the STRICT screen, best-first.
                      each needs at least {"ticker": str}; price/symbol carried through.
    hold_ok         : set of currently-held tickers that still pass the LOOSE hold test.
    state           : {"last_rebalance": iso|None, "positions": {tk: {...,"days_out","entered"}}}
    returns         : (target_tickers, new_state, log, is_rebalance_day)
    """
    c = {**DEFAULTS, **(cfg or {})}
    positions = {tk: dict(p) for tk, p in state.get("positions", {}).items()}
    log = []

    # 1) update the "days failing the hold test" counter for every holding
    for tk, p in positions.items():
        p["days_out"] = 0 if tk in hold_ok else p.get("days_out", 0) + 1

    # 2) exits: anything that has failed the hold test for >= grace days (any day)
    for tk in [t for t, p in positions.items() if p["days_out"] >= c["EXIT_GRACE_DAYS"]]:
        positions.pop(tk)
        log.append(("EXIT", tk, f"failed hold {c['EXIT_GRACE_DAYS']}d"))

    # 3) is today a rebalance day? weekly, or if a week has lapsed, or first run
    last = _as_date(state.get("last_rebalance"))
    days_since = (today - last).days if last else 10 ** 6
    is_rebal = last is None or today.weekday() == c["REBALANCE_WEEKDAY"] or days_since >= 7

    # 4) on a rebalance day, fill empty slots with the best entrants (no forced rotation)
    if is_rebal:
        slots = c["MAX_POSITIONS"] - len(positions)
        for s in entry_survivors:
            if slots <= 0:
                break
            tk = s["ticker"]
            if tk not in positions:
                positions[tk] = {"days_out": 0, "entered": today.isoformat(),
                                 "symbol": s.get("symbol"), "price": s.get("price")}
                log.append(("ENTER", tk, "passed entry screen"))
                slots -= 1
        new_last = today.isoformat()
    else:
        new_last = state.get("last_rebalance")

    new_state = {"last_rebalance": new_last, "positions": positions}
    return list(positions.keys()), new_state, log, is_rebal
