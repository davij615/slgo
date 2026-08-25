// api/_signals.js — shared momentum math (mirrors engine/signals.py).
// Underscore prefix => Vercel does not treat this as a route.

export const mom121 = (py, p1m) =>
  py == null ? null : (1 + py / 100) / (1 + (p1m || 0) / 100) - 1;
export const riskAdj = (m, v) =>
  m == null || v == null ? null : m / Math.max(Math.abs(v), 1e-6);
export const h52 = (c, h) => (!c || !h ? null : c / h);

export function zscores(vals) {
  const xs = vals.filter((v) => v != null && !Number.isNaN(v));
  if (xs.length < 2) return vals.map((v) => (v == null ? null : 0));
  const m = xs.reduce((a, b) => a + b, 0) / xs.length;
  const sd = Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / xs.length) || 1;
  return vals.map((v) => (v == null ? null : (v - m) / sd));
}

const W = { ra: 0.5, h52: 0.25, sec: 0.25 };

// rows need normalized keys: { mom121, vol, close, high_52w, sector }
export function composite(rows) {
  const secSum = {}, secN = {};
  rows.forEach((r) => {
    if (r.mom121 != null && r.sector) {
      secSum[r.sector] = (secSum[r.sector] || 0) + r.mom121;
      secN[r.sector] = (secN[r.sector] || 0) + 1;
    }
  });
  const secMean = (s) => (secN[s] ? secSum[s] / secN[s] : null);
  const ra = zscores(rows.map((r) => riskAdj(r.mom121, r.vol)));
  const hh = zscores(rows.map((r) => h52(r.close, r.high_52w)));
  const sr = zscores(rows.map((r) =>
    r.mom121 != null && secMean(r.sector) != null ? r.mom121 - secMean(r.sector) : null));
  return rows.map((_, i) => {
    let s = 0;
    if (ra[i] != null) s += W.ra * ra[i];
    if (hh[i] != null) s += W.h52 * hh[i];
    if (sr[i] != null) s += W.sec * sr[i];
    return s;
  });
}

// rows need normalized keys; attaches .score and returns rows
export function scoreRows(rows, method) {
  if (method === "composite") {
    const sc = composite(rows);
    rows.forEach((r, i) => { r.score = sc[i]; });
  } else {
    rows.forEach((r) => {
      r.score =
        method === "raw" ? (r.perf_1m || 0) + (r.perf_3m || 0)
        : method === "mom121" ? r.mom121
        : method === "riskadj" ? riskAdj(r.mom121, r.vol)
        : r.chg1m;  // "chg" — original 1-month-change order
    });
  }
  return rows;
}
