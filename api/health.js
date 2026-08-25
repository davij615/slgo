// api/health.js — momentum leaders in the HEALTH universe only.
// Sectors: "Health Technology" (pharma/biotech/devices) + "Health Services"
// (managed care/insurers, hospitals, services). Biotech-tuned gates: lower
// cap/price/liquidity floors, profitability gate OFF by default (biotech is
// pre-revenue). ?quality=1 re-enables ROE>0 (quality tilt, drops most biotech).
//   ?method=raw|mom121|riskadj|composite (default)   ?n=5|10|20
import { mom121, scoreRows } from "./_signals.js";

const HEALTH_SECTORS = ["Health Technology", "Health Services"];
const COLUMNS = [
  "name", "description", "close", "Perf.1M", "Perf.3M", "Perf.Y", "Volatility.D",
  "price_52_week_high", "Recommend.All", "ADX", "market_cap_basic",
  "average_volume_30d_calc", "exchange", "sector", "industry", "return_on_equity",
];
const MIN_DOLLAR_VOLUME = 3_000_000;
const HIGH_PROXIMITY = 0.70;

const FILTERS = [
  { left: "sector", operation: "in_range", right: HEALTH_SECTORS },
  { left: "exchange", operation: "in_range", right: ["NASDAQ", "NYSE", "AMEX"] },
  { left: "close", operation: "egreater", right: 5 },
  { left: "market_cap_basic", operation: "egreater", right: 300000000 },
  { left: "Perf.1M", operation: "egreater", right: 10 },
  { left: "Perf.3M", operation: "egreater", right: 15 },
  { left: "Recommend.All", operation: "egreater", right: -0.1 },
  { left: "ADX", operation: "egreater", right: 20 },
  { left: "close", operation: "greater", right: "SMA50" },
  { left: "SMA50", operation: "greater", right: "SMA200" },
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
  sort: { sortBy: "Perf.3M", sortOrder: "desc", nullsFirst: false },
  range: [0, 150], ignore_unknown_fields: false,
};

export default async function handler(req, res) {
  const n = Math.min(Math.max(parseInt(req.query?.n) || 10, 1), 25);
  const method = ["raw", "mom121", "riskadj", "composite"].includes(req.query?.method)
    ? req.query.method : "composite";
  const quality = req.query?.quality === "1";
  const full = req.query?.full === "1";   // return all eligible (for balanced book)
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
      o.mom121 = mom121(o["Perf.Y"], o["Perf.1M"]);
      o.vol = o["Volatility.D"]; o.high_52w = o["price_52_week_high"];
      o.perf_1m = o["Perf.1M"]; o.perf_3m = o["Perf.3M"];
      return o;
    });
    rows = rows
      .filter((r) => (r.close || 0) * (r.average_volume_30d_calc || 0) >= MIN_DOLLAR_VOLUME)
      .filter((r) => !r.price_52_week_high || r.close >= HIGH_PROXIMITY * r.price_52_week_high);
    if (quality) rows = rows.filter((r) => r.return_on_equity == null || r.return_on_equity > 0);

    scoreRows(rows, method);
    rows.sort((a, b) => (b.score ?? -1e9) - (a.score ?? -1e9));
    const slice = full ? rows.slice(0, 150) : rows.slice(0, n);
    const top = slice.map((r) => ({
      ...r, score: r.score == null ? null : +r.score.toFixed(3),
      mom121: r.mom121 == null ? null : +(r.mom121 * 100).toFixed(1),
    }));
    // sub-industry mix across the full eligible set
    const mix = {};
    rows.forEach((r) => { const k = r.industry || "Other"; mix[k] = (mix[k] || 0) + 1; });
    res.setHeader("Cache-Control", "s-maxage=3600, stale-while-revalidate=86400");
    res.status(200).json({
      asOf: new Date().toISOString(), strategy: `health-${method}${full ? "-full" : `-top${n}`}${quality ? "-q" : ""}`,
      method, quality, full, total: rows.length, count: top.length, mix, rows: top,
    });
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
}
