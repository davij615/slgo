// api/momentum.js — live multi-timeframe momentum for a set of tickers.
// ?symbols=NASDAQ:AAPL,NYSE:XYZ  (full exchange:ticker, comma-separated, up to 30)
// Returns per stock: perf across 1W/1M/3M/6M/1Y, per-month rate term structure,
// acceleration, strength (0-100), state (accelerating/steady/fading/reversing),
// and a fizzling flag. Frontend feeds it the current strategy's picks.
import { momentumState } from "./_momentum.js";

const COLUMNS = [
  "name", "description", "close", "Perf.W", "Perf.1M", "Perf.3M", "Perf.6M",
  "Perf.Y", "ADX", "RSI", "SMA20", "price_52_week_high",
];

export default async function handler(req, res) {
  const raw = (req.query?.symbols || "").split(",").map((s) => s.trim()).filter(Boolean).slice(0, 30);
  if (!raw.length) { res.status(400).json({ error: "pass ?symbols=EX:TICK,EX:TICK" }); return; }
  const payload = {
    symbols: { tickers: raw, query: { types: [] } },
    columns: COLUMNS, range: [0, raw.length], ignore_unknown_fields: false,
  };
  try {
    const tv = await fetch("https://scanner.tradingview.com/america/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json", "User-Agent": "Mozilla/5.0" },
      body: JSON.stringify(payload),
    });
    if (!tv.ok) { res.status(502).json({ error: `TradingView ${tv.status}` }); return; }
    const json = await tv.json();
    const rows = (json.data || []).map((row) => {
      const o = {}; COLUMNS.forEach((c, i) => { o[c] = row.d[i]; });
      const st = momentumState(o);
      return {
        symbol: row.s, ticker: o.name, company: o.description, close: o.close,
        perf: { w: o["Perf.W"], m1: o["Perf.1M"], m3: o["Perf.3M"], m6: o["Perf.6M"], y: o["Perf.Y"] },
        ...st,
      };
    });
    // most accelerating first, fizzling/reversing last
    rows.sort((a, b) => (b.accel ?? -1e9) - (a.accel ?? -1e9));
    res.setHeader("Cache-Control", "s-maxage=1800, stale-while-revalidate=43200");
    res.status(200).json({ asOf: new Date().toISOString(), count: rows.length, rows });
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
}
