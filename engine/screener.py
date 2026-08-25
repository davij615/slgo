"""
Stock Screener — replicates the TradingView screener from the screenshot
========================================================================
Saved name: "May 12th (1 Bil MC, Strong Buy+Strong Buy + Buy, +15% Monthly, 2B)"

Every filter in that screen is a native TradingView metric, so this script talks
straight to TradingView's scanner API (the same data the website uses) via the
`tradingview-screener` package instead of trying to recompute TV's proprietary
Tech/MA/Oscillator ratings from raw prices.

    pip install tradingview-screener pandas
    python screener.py

NOTE ON THE SCREENSHOT
----------------------
The saved *name* ("1 Bil MC ... +15% Monthly") doesn't match the *active* filter
chips, which is normal — the name is a label from when it was first saved, the
chips are the current values. This script follows the ACTIVE CHIPS:

    Country .............. US
    Market cap ........... > 500M USD          (name says 1B — see MARKET_CAP_MIN)
    Change, 1M ........... > 5%                 (name says +15% — see CHANGE_1M_MIN)
    Perf, 1W ............. > 0%
    Analyst rating ....... 2 buckets selected   -> Strong Buy + Buy
    Tech rating, 1M ...... 3 buckets selected   -> Strong Buy + Buy + Neutral
    MA rating, 1M ........ 3 buckets selected   -> Strong Buy + Buy + Neutral
    Os (oscillator), 1M .. 3 buckets selected   -> Strong Buy + Buy + Neutral
    ADX(14) .............. > 40
    Volatility ........... < 5%

Anything in the screenshot shown only as an empty dropdown (Watchlist, Index,
Price, P/E, EPS dil growth, Div yield, Sector, Revenue growth, PEG, ROE, Beta,
earnings dates) had no value set, so it is not filtered here. Each one is left
as a commented stub at the bottom so you can switch it on.
"""

from tradingview_screener import Query, col
import pandas as pd

# ───────────────────────────── CONFIG (edit me) ─────────────────────────────
MARKET           = "america"        # TradingView market for the "US" flag
MARKET_CAP_MIN   = 500_000_000      # > 500M USD. Set 1_000_000_000 to match the name.
CHANGE_1M_MIN    = 5                # "Chg, 1M" > 5 (%). Set 15 to match the name.
PERF_1W_MIN      = 0                # "Perf, 1W" > 0 (%)
ADX_MIN          = 40               # ADX(14) > 40 (strong trend)
VOLATILITY_MAX   = 5                # Volatility < 5 (%)
MIN_DOLLAR_VOLUME = 5_000_000       # avg daily $ volume floor — fillable orders
RESULT_LIMIT     = 100              # max rows to pull back
SORT_BY          = "change|1M"      # sort field (a column name below)
SORT_DESC        = True

# Which rating buckets to ALLOW for each filter. Edit these lists to widen/narrow.
# (The chips showed "2" for analyst and "3" for each technical rating.)
ANALYST_ALLOWED  = ["strong_buy", "buy"]                 # the "(2)" chip
TECH_ALLOWED     = ["strong_buy", "buy", "neutral"]      # the "(3)" chip
MA_ALLOWED       = ["strong_buy", "buy", "neutral"]      # the "(3)" chip
OS_ALLOWED       = ["strong_buy", "buy", "neutral"]      # the "(3)" chip
# ─────────────────────────────────────────────────────────────────────────────


# TradingView technical ratings (Recommend.*) are floats in [-1, 1].
# These are TV's standard category cut-offs:
TECH_BUCKETS = {
    "strong_buy":  (0.5,  1.0),
    "buy":         (0.1,  0.5),
    "neutral":     (-0.1, 0.1),
    "sell":        (-0.5, -0.1),
    "strong_sell": (-1.0, -0.5),
}

# Analyst rating (recommendation_mark) is a float in [1, 5], 1 = most bullish.
ANALYST_BUCKETS = {
    "strong_buy":  (1.0, 1.5),
    "buy":         (1.5, 2.5),
    "neutral":     (2.5, 3.5),
    "sell":        (3.5, 4.5),
    "strong_sell": (4.5, 5.0),
}


def range_for(buckets: dict, allowed: list[str]) -> tuple[float, float]:
    """Collapse a set of allowed (contiguous) buckets into one [low, high] range."""
    chosen = [buckets[name] for name in allowed]
    return min(lo for lo, _ in chosen), max(hi for _, hi in chosen)


def build_query() -> Query:
    tech_lo, tech_hi = range_for(TECH_BUCKETS, TECH_ALLOWED)
    ma_lo,   ma_hi   = range_for(TECH_BUCKETS, MA_ALLOWED)
    os_lo,   os_hi   = range_for(TECH_BUCKETS, OS_ALLOWED)
    an_lo,   an_hi   = range_for(ANALYST_BUCKETS, ANALYST_ALLOWED)

    columns = [
        "name", "description", "close", "market_cap_basic",
        "change|1M", "Perf.W",
        "recommendation_mark",
        "Recommend.All|1M", "Recommend.MA|1M", "Recommend.Other|1M",
        "ADX", "Volatility.D", "sector", "average_volume_30d_calc",
    ]

    return (
        Query()
        .set_markets(MARKET)
        .select(*columns)
        .where(
            col("market_cap_basic")  >= MARKET_CAP_MIN,        # Mkt cap > 500M
            col("change|1M")          >= CHANGE_1M_MIN,        # Chg, 1M > 5%
            col("Perf.W")             >  PERF_1W_MIN,          # Perf, 1W > 0%
            col("ADX")                >  ADX_MIN,              # ADX(14) > 40
            col("Volatility.D")       <  VOLATILITY_MAX,       # Volatility < 5%
            col("recommendation_mark").between(an_lo,  an_hi), # Analyst rating
            col("Recommend.All|1M")   .between(tech_lo, tech_hi),  # Tech rating, 1M
            col("Recommend.MA|1M")    .between(ma_lo,  ma_hi),     # MA rating, 1M
            col("Recommend.Other|1M") .between(os_lo,  os_hi),     # Os rating, 1M
        )
        .order_by(SORT_BY, ascending=not SORT_DESC)
        .limit(RESULT_LIMIT)
    )

    # ── Stubs for the empty dropdowns in the screenshot (uncomment to use) ──
    #   col("price_earnings_ttm").between(0, 30)         # P/E
    #   col("dividends_yield")          > 2              # Div yield %
    #   col("return_on_equity")         > 15            # ROE
    #   col("beta_1_year").between(0, 1.5)              # Beta
    #   col("revenue_growth")           > 10           # Revenue growth (YoY %)
    #   col("price_earnings_growth").between(0, 2)     # PEG
    #   col("sector").isin(["Technology", "Healthcare"])
    #   col("close").between(5, 500)                   # Price
    #   col("earnings_release_next_date").in_day_range(0, 14)  # Upcoming earnings


def label_rating(value: float, buckets: dict) -> str:
    for name, (lo, hi) in buckets.items():
        if lo <= value <= hi:
            return name.replace("_", " ").title()
    return "—"


def main() -> None:
    count, df = build_query().get_scanner_data()

    # liquidity: keep names with enough average daily dollar volume to fill
    if not df.empty and "average_volume_30d_calc" in df:
        dollar_vol = df["close"] * df["average_volume_30d_calc"]
        df = df[dollar_vol >= MIN_DOLLAR_VOLUME]

    print(f"\nMatches in market '{MARKET}': {len(df)} of {count} "
          f"(after liquidity filter, showing up to {RESULT_LIMIT})\n")

    if df.empty:
        print("No stocks matched. Loosen a threshold and rerun.")
        return

    # Pretty labels for the human-readable ratings
    df["Tech"] = df["Recommend.All|1M"].map(lambda v: label_rating(v, TECH_BUCKETS))
    df["Analyst"] = df["recommendation_mark"].map(lambda v: label_rating(v, ANALYST_BUCKETS))

    view = df[[
        "name", "description", "close", "market_cap_basic",
        "change|1M", "Perf.W", "ADX", "Volatility.D", "Tech", "Analyst",
    ]].rename(columns={
        "name": "Ticker", "description": "Company", "close": "Price",
        "market_cap_basic": "MktCap", "change|1M": "Chg1M%",
        "Perf.W": "Perf1W%", "Volatility.D": "Vol%",
    })
    view["MktCap"] = (view["MktCap"] / 1e9).round(2).astype(str) + "B"

    pd.set_option("display.max_rows", None, "display.width", 200)
    print(view.to_string(index=False))

    out = "screener_results.csv"
    df.to_csv(out, index=False)
    print(f"\nFull data saved to {out}")


if __name__ == "__main__":
    main()
