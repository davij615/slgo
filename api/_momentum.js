// api/_momentum.js — momentum term-structure & "fizzling" math (pure, tested).
// Underscore prefix => not a Vercel route.
//
// Idea: each TradingView Perf.* window is a trailing cumulative return over a
// different length. Divide each by its length to get a comparable ~monthly rate.
// If the RECENT rate (1W/1M) has dropped below the OLDER rate (3M/6M), momentum
// is decelerating — fizzling. If recent > older, it's accelerating.

const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
const avg = (xs) => { const v = xs.filter((x) => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };

// multiply each window's total % return by this to get an approx per-month rate
export const PER_MONTH = { w: 4, m1: 1, m3: 1 / 3, m6: 1 / 6, y: 1 / 12 };

export function monthlyRates(perf) {
  return {
    w: perf.w == null ? null : perf.w * PER_MONTH.w,
    m1: perf.m1 == null ? null : perf.m1 * PER_MONTH.m1,
    m3: perf.m3 == null ? null : perf.m3 * PER_MONTH.m3,
    m6: perf.m6 == null ? null : perf.m6 * PER_MONTH.m6,
    y: perf.y == null ? null : perf.y * PER_MONTH.y,
  };
}

// recent monthly pace minus older monthly pace (points/month). >0 accelerating.
export function acceleration(rates) {
  const recent = avg([rates.w, rates.m1]);
  const base = avg([rates.m3, rates.m6]);
  return recent == null || base == null ? null : recent - base;
}

export function classify(perf, accel, ctx) {
  const shortNeg = (perf.w != null && perf.w < 0) || (perf.m1 != null && perf.m1 < 0);
  const longPos = perf.m3 != null && perf.m3 > 0;
  if (shortNeg && longPos) return "reversing";
  if (accel != null && accel <= -1) return "fading";
  if (accel != null && accel >= 1) return "accelerating";
  return "steady";
}

// 0-100: trend strength (ADX) blended with how many windows are positive
export function strength(adx, perf) {
  const adxScore = adx == null ? 40 : clamp((adx - 15) / (50 - 15), 0, 1) * 100;
  const wins = [perf.w, perf.m1, perf.m3, perf.m6, perf.y].filter((x) => x != null);
  const consistency = wins.length ? wins.filter((x) => x > 0).length / wins.length : 0;
  return Math.round(0.6 * adxScore + 0.4 * consistency * 100);
}

export function momentumState(row) {
  const perf = { w: row["Perf.W"], m1: row["Perf.1M"], m3: row["Perf.3M"], m6: row["Perf.6M"], y: row["Perf.Y"] };
  const rates = monthlyRates(perf);
  const accel = acceleration(rates);
  const belowSMA20 = row.SMA20 != null && row.close != null ? row.close < row.SMA20 : false;
  const fromHigh = row.price_52_week_high ? (row.price_52_week_high - row.close) / row.price_52_week_high : null;
  const state = classify(perf, accel, { belowSMA20, fromHigh, adx: row.ADX });
  const fizzling = accel != null && accel < 0 && (belowSMA20 || (perf.w != null && perf.w < 0));
  return {
    perf, rates,
    accel: accel == null ? null : +accel.toFixed(2),
    state, strength: strength(row.ADX, perf), fizzling,
    adx: row.ADX == null ? null : +row.ADX.toFixed(0),
    rsi: row.RSI == null ? null : +row.RSI.toFixed(0),
    fromHigh: fromHigh == null ? null : +(fromHigh * 100).toFixed(1),
    belowSMA20,
  };
}
