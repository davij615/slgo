// portfolio.js — build the balanced health book (pure, testable).
// Group passing names by sub-industry; within each group take the single best
// large-cap and single best small-cap by composite score; weight by adjustable
// conviction (score-tilted) and a large/small tilt.

export function buildBook(rows, capLine, groupKey = "sector") {
  const groups = {};
  for (const r of rows) {
    const g = r[groupKey] || "Other";
    (groups[g] ||= []).push(r);
  }
  const picks = [];
  for (const [group, list] of Object.entries(groups)) {
    const sorted = [...list].sort((a, b) => (b.score ?? -1e9) - (a.score ?? -1e9));
    const large = sorted.find((r) => (r.market_cap_basic || 0) >= capLine);
    const small = sorted.find((r) => (r.market_cap_basic || 0) < capLine);
    if (large) picks.push({ ...large, group, tier: "large" });
    if (small) picks.push({ ...small, group, tier: "small" });
  }
  return picks;
}

// conviction: 0 = equal weight, 1 = fully score-tilted.
// tilt: -1..1, positive favors large caps, negative favors small.
export function computeWeights(picks, { conviction = 0.5, tilt = 0 } = {}) {
  const n = picks.length;
  if (!n) return [];
  const scores = picks.map((p) => (p.score == null ? 0 : p.score));
  const min = Math.min(...scores), max = Math.max(...scores);
  const range = max - min;
  const eps = range > 0 ? 0.1 * range : 1; // lowest name still gets a slice
  const shifted = scores.map((s) => s - min + eps);
  const sumShift = shifted.reduce((a, b) => a + b, 0);
  const eq = 1 / n;
  // blend equal vs conviction
  let w = picks.map((_, i) => (1 - conviction) * eq + conviction * (shifted[i] / sumShift));
  // large/small tilt
  w = w.map((wi, i) => wi * (picks[i].tier === "large" ? 1 + tilt : 1 - tilt));
  const sum = w.reduce((a, b) => a + b, 0) || 1;
  return w.map((wi) => wi / sum);
}

// integer-share sizing from weights and capital
export function sizeBook(picks, weights, capital) {
  let spent = 0;
  const out = picks.map((p, i) => {
    const target = capital * weights[i];
    const shares = p.close ? Math.floor(target / p.close) : 0;
    const value = shares * (p.close || 0);
    spent += value;
    return { ...p, weight: weights[i], shares, value };
  });
  return { rows: out, cash: capital - spent };
}
