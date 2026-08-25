"""
signals.py — the enhanced momentum math (pure, offline-testable).

Implements the research-backed upgrades to the ranking signal:

  • 12-1 momentum (skip the most recent month)   Jegadeesh & Titman 1993
  • risk-adjusted momentum (÷ volatility)         Barroso & Santa-Clara 2015
  • 52-week-high proximity                         George & Hwang 2004
  • sector-relative momentum (residual proxy)      Moskowitz & Grinblatt 1999
  • Frog-in-the-Pan smoothness (info discreteness) Da, Gurun & Warachka 2014

The composite score is a cross-sectional z-score blend of the first four. FIP is
applied as a second-stage screen and needs daily bars (see momentum_pro.py).
Everything here is a pure function of numbers, so it's fully unit-tested.
"""
from __future__ import annotations
import math
from collections import defaultdict


def mom_12_1(perf_y, perf_1m):
    """12-1 momentum from TradingView's 1-year and 1-month performance (percent).
    Removes the most recent month: (1+Y)/(1+1M) - 1. Skipping the recent month
    dodges short-term reversal — the core fix vs. the old (1M+3M) score."""
    if perf_y is None:
        return None
    y = perf_y / 100.0
    m = (perf_1m or 0) / 100.0
    if (1 + m) == 0:
        return None
    return (1 + y) / (1 + m) - 1


def risk_adjusted(mom, vol):
    """Momentum per unit volatility. Tilts toward persistent movers over jumpy
    pops — the single biggest robustness upgrade from existing fields."""
    if mom is None or vol is None:
        return None
    return mom / max(abs(vol), 1e-6)


def high_52w_ratio(close, high_52w):
    """Proximity to the 52-week high (1.0 = at the high). Standalone momentum
    signal that, in the US, dominated past-return momentum (George & Hwang)."""
    if not close or not high_52w:
        return None
    return close / high_52w


def sector_means(rows, key="mom121", sector_key="sector"):
    """Mean 12-1 momentum per sector across the candidate cross-section."""
    agg = defaultdict(list)
    for r in rows:
        v, s = r.get(key), r.get(sector_key)
        if v is not None and s:
            agg[s].append(v)
    return {s: sum(v) / len(v) for s, v in agg.items() if v}


def sector_relative(mom, sector_mean):
    """Stock momentum minus its sector's momentum — a practical residual-
    momentum proxy that strips out the industry component."""
    if mom is None or sector_mean is None:
        return None
    return mom - sector_mean


def zscores(values):
    """Cross-sectional z-scores; None preserved, single-value lists -> 0."""
    xs = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if len(xs) < 2:
        return [0.0 if v is not None else None for v in values]
    mean = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / len(xs)) or 1.0
    return [None if v is None else (v - mean) / sd for v in values]


DEFAULT_WEIGHTS = {"ra": 0.50, "h52": 0.25, "sec": 0.25}


def composite_scores(rows, weights=None):
    """Blend z-scored (risk-adjusted 12-1, 52w-high ratio, sector-relative 12-1).
    rows need: mom121, vol, close, high_52w, sector. Returns list of floats."""
    w = weights or DEFAULT_WEIGHTS
    secm = sector_means(rows)
    ra = zscores([risk_adjusted(r.get("mom121"), r.get("vol")) for r in rows])
    h52 = zscores([high_52w_ratio(r.get("close"), r.get("high_52w")) for r in rows])
    sec = zscores([sector_relative(r.get("mom121"), secm.get(r.get("sector"))) for r in rows])
    out = []
    for i in range(len(rows)):
        parts = [(w["ra"], ra[i]), (w["h52"], h52[i]), (w["sec"], sec[i])]
        out.append(sum(wt * z for wt, z in parts if z is not None))
    return out


def score_one(method, row):
    """Single-row score for the variants you can race (no cross-section needed
    for raw/mom121/riskadj; composite is computed in batch by composite_scores)."""
    if method == "raw":
        return (row.get("perf_1m") or 0) + (row.get("perf_3m") or 0)
    if method == "mom121":
        return row.get("mom121")
    if method == "riskadj":
        return risk_adjusted(row.get("mom121"), row.get("vol"))
    raise ValueError(f"use composite_scores() for method={method}")


def information_discreteness(daily_returns):
    """Frog-in-the-Pan: ID = sign(PRET) * (%down_days - %up_days) over the
    formation window. NEGATIVE = smooth/continuous = higher-quality momentum;
    keep the most negative. Needs daily returns (fractions), so engine-only."""
    rets = [r for r in daily_returns if r is not None]
    n = len(rets)
    if n < 20:
        return None
    pret, up, down = 1.0, 0, 0
    for r in rets:
        pret *= (1 + r)
        if r > 0:
            up += 1
        elif r < 0:
            down += 1
    pret -= 1
    sign = 1 if pret > 0 else (-1 if pret < 0 else 0)
    return sign * ((down / n) - (up / n))
