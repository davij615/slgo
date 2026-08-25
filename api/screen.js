// api/screen.js — CONSERVATIVE screen, live, whole US market.
// Returns all liquid survivors of the picture's filters; optionally ranks and
// caps to the top N by a chosen method.
//   ?n=5|10|20   cap to top N (omit for all survivors)
//   ?method=composite|mom121|riskadj|chg   ranking (default composite)
// Browsers can't call TradingView directly (CORS) — this function proxies it.
import { mom121, scoreRows } from "./_signals.js";

const COLUMNS = [
  "name", "description", "close", "market_cap_basic", "change|1M", "Perf.W",
  "Perf.Y", "ADX", "Volatility.D", "Recommend.All|1M", "Recommend.MA|1M",
  "Recommend.Other|1M", "recommendation_mark", "sector", "volume",
  "average_volume_30d_calc", "price_52_week_high",
];
const MIN_DOLLAR_VOLUME = 5_000_000;

const FILTERS = [
  { left: "market_cap_basic", operation: "egreater", right: 500000000 },
  { left: "change|1M", operation: "egreater", right: 5 },
  { left: "Perf.W", operation: "greater", right: 0 },
  { left: "ADX", operation: "greater", right: 40 },
  { left: "Volatility.D", operation: "less", right: 5 },
  { left: "recommendation_mark", operation: "in_range", right: [1, 2.5] },
  { left: "Recommend.All|1M", operation: "in_range", right: [-0.1, 1] },
  { left: "Recommend.MA|1M", operation: "in_range", right: [-0.1, 1] },
  { left: "Recommend.Other|1M", operation: "in_range", right: [-0.1, 1] },
];
const STOCK_TYPES = {
  operator: "and",
  operands: [
    { operation: { operator: "or", operands: [
      { operation: { operator: "and", operands: [
        { expression: { left: "type", operation: "equal", right: "stock" } },
        { expression: { left: "typespecs", operation: "has", right: ["common"] } },
      ] } },
      { operation: { operator: "and", operands: [
        { expression: { left: "type", operation: "equal", right: "dr" } },
      ] } },
    ] } },
    { expression: { left: "typespecs", operation: "has_none_of", right: ["pre-ipo"] } },
  ],
};
const PAYLOAD = {
  markets: ["america"], symbols: {}, options: { lang: "en" }, columns: COLUMNS,
  filter: FILTERS, filter2: STOCK_TYPES,
  sort: { sortBy: "change|1M", sortOrder: "desc", nullsFirst: false },
  range: [0, 300], ignore_unknown_fields: false,
};

export default async function handler(req, res) {
  const n = req.query?.n ? Math.min(Math.max(parseInt(req.query.n), 1), 100) : null;
  const method = ["composite", "mom121", "riskadj", "chg"].includes(req.query?.method)
    ? req.query.method : "composite";
  try {
    const tv = await fetch("https://scanner.tradingview.com/america/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json", "User-Agent": "Mozilla/5.0" },
      body: JSON.stringify(PAYLOAD),
    });
    if (!tv.ok) { res.status(502).json({ error: `TradingView ${tv.status}` }); return; }
    const json = await tv.json();
    let rows = (json.data || []).map((row) => {
      const o = {}; COLUMNS.forEach((c, i) => { o[c] = row.d[i]; });
      o.symbol = row.s;
      // normalized keys for scoring
      o.mom121 = mom121(o["Perf.Y"], o["change|1M"]);
      o.vol = o["Volatility.D"]; o.high_52w = o["price_52_week_high"];
      o.chg1m = o["change|1M"];
      return o;
    });
    rows = rows.filter(
      (r) => (r.close || 0) * (r.average_volume_30d_calc || 0) >= MIN_DOLLAR_VOLUME);

    scoreRows(rows, method);
    if (n) rows.sort((a, b) => (b.score ?? -1e9) - (a.score ?? -1e9));
    const out = (n ? rows.slice(0, n) : rows).map((r) => ({
      ...r, score: r.score == null ? null : +r.score.toFixed(3),
      mom121: r.mom121 == null ? null : +(r.mom121 * 100).toFixed(1),
    }));
    res.setHeader("Cache-Control", "s-maxage=3600, stale-while-revalidate=86400");
    res.status(200).json({
      asOf: new Date().toISOString(), strategy: n ? `conservative-${method}-top${n}` : "conservative-all",
      method, total: rows.length, count: out.length, rows: out,
    });
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
}
