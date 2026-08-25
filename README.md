# Quant Lab — live screen + daily target sheet

Your screener (from the picture), run **live** across the **entire US tradeable
market**, plus the first rung of going live: a **daily target sheet** that sizes
the survivors into your account and emails you an exact BUY / SELL / HOLD list.
It places **no orders** — you trade the sheet by hand.

```
quant-lab/
├── api/screen.js          serverless fn: runs the screen live on TradingView
├── index.html  package.json  src/        the dashboard (Vite + React)
│                                          — live survivors + position sizing
├── engine/                Python (local + CI, never on Vercel)
│   ├── screener.py           interactive local run — prints today's survivors
│   ├── snapshot.py           strict + loose screen queries; logs daily survivors
│   ├── portfolio.py          turnover-reduction logic (weekly + hysteresis)
│   └── daily_target.py       sizing + buy/sell/hold diff + email
└── .github/workflows/
    ├── snapshot.yml          daily: record survivors (forward track record)
    └── daily-target.yml      daily: build + email the target sheet
```

## The strategy (the picture, whole market)

| filter | rule |   | filter | rule |
|---|---|---|---|---|
| Market cap | > 500M | | ADX(14) | > 40 |
| Change, 1M | > 5% | | Volatility | < 5% |
| Perf, 1W | > 0% | | Analyst | Strong Buy / Buy |
| Tech / MA / Os 1M | Buy+ | | | |

Filters live in `api/screen.js` (site) and the Python (`snapshot.py` /
`daily_target.py`). "Survivors" = whatever passes today.

## Rung 1 — the daily target sheet

```bash
cd engine && pip install -r requirements.txt
ACCOUNT_SIZE=10000 MAX_POSITIONS=20 python daily_target.py --dry-run
```

It runs the screen, equal-weights the top N survivors into your capital (integer
shares), diffs against `public/portfolio/holdings.json`, and prints/saves/emails:

```
BUY    19 NVDA  @ ~$128.00
SELL   40 KO
HOLD   ... 
```

`--dry-run` previews without touching holdings. A real run assumes you executed
the sheet and records the new holdings so tomorrow's diff is correct. **It never
places orders.** The website also sizes the live list client-side — type your
capital and it shows share counts and cash left.

### Email (opt-in, your own credentials)

Email sends only if these are set; the script just reads them from the
environment — it never sees or stores your credentials:

| env var | example |
|---|---|
| `SMTP_HOST` / `SMTP_PORT` | `smtp.gmail.com` / `465` |
| `SMTP_USER` / `SMTP_PASS` | your address / an **app password**, not your login |
| `EMAIL_FROM` / `EMAIL_TO` | where it's from / where it lands |

In GitHub: add these as **repo Secrets**, and `ACCOUNT_SIZE` / `MAX_POSITIONS`
as **repo Variables**. The `daily-target.yml` Action runs after the US close,
emails the sheet, and commits it. Give Actions write access:
**Settings → Actions → General → Workflow permissions → Read and write.**

## Two strategies, one engine

**Conservative** (`daily_target.py`) — the picture's screen over the whole market,
weekly rebalance with hysteresis. Now also **rank-and-select**: set
`MAX_POSITIONS=5|10|20` to hold a top-N book, and `RANK_METHOD` (composite default,
or `mom121`/`riskadj`/`chg`) to choose how empty slots are filled — so the engine
picks the best-ranked qualifiers instead of just the highest 1-month change. Set
`MAX_POSITIONS` high to keep the original "hold everything that qualifies" behavior.
The web view has matching top-N (All/5/10/20) and rank controls.

**Aggressive momentum leaders** (`aggressive.py`) — the challenger, now with
research-backed ranking. Eligibility (whole listed market, no OTC): $10+ price,
$1B+ cap, $20M+ daily dollar volume, uptrend stack (close > 50 > 200-day MA),
near 52-week highs, strong 1M/3M, Buy+ rating, and a profitability gate (ROE > 0)
to avoid junk rallies.

**Ranking** is selectable via `RANK_METHOD` (race them with `STRATEGY_TAG`):

| method | signal | evidence |
|---|---|---|
| `raw` | Perf 1M + 3M (old) | baseline — reversal-prone |
| `mom121` | 12-month return **skipping the last month** | Jegadeesh & Titman |
| `riskadj` | 12-1 ÷ volatility | Barroso & Santa-Clara |
| `composite` *(default)* | z-blend of risk-adj 12-1 + 52-week-high + sector-relative 12-1 | George & Hwang; Moskowitz & Grinblatt |

Why the change: the old `1M + 3M` score over-weighted the most recent month,
which mean-reverts. The composite skips it, divides by volatility (favoring
smooth movers over jumpy pops), rewards 52-week-high leadership, and nets out the
sector component as a residual-momentum proxy.

```bash
cd engine
RANK_METHOD=composite python aggressive.py --dry-run      # the upgraded ranking
RANK_METHOD=raw STRATEGY_TAG=baseline python aggressive.py --dry-run   # race the old one
FIP_ENABLED=1 python aggressive.py --dry-run              # + Frog-in-the-Pan smoothness
```

**Optional second stage — `FIP_ENABLED=1`**: applies Frog-in-the-Pan smoothness
(Da/Gurun/Warachka) to the top pool using daily bars (yfinance), keeping the
smoothest names — the way Alpha Architect's QMOM refines its list. Engine-only
(needs daily history, not a single scanner field).

**Documented but not shipped** (need a paid feed, so no fake data): earnings-
estimate-revision / SUE momentum has strong, orthogonal evidence — wire your
estimates feed into `fetch_earnings_revision()` to blend it in. Full residual
momentum (rolling factor regression) is approximated here by sector-relative.

The website's aggressive view has a `rank` selector (composite / risk-adj / 12-1
/ raw) and a 5/10 toggle, all live. The full evidence brief is in the research
report shared in chat.



Rebalancing daily and dumping a name the moment it leaves the screen is the
fastest way to bleed money to spreads and short-term taxes. Three guards cut the
churn ~80% in simulation without abandoning the signal:

- **Weekly rebalance** — new positions are added only on `REBALANCE_WEEKDAY`
  (default Monday) or if a week has lapsed. A hot name appearing on a Wednesday
  waits for Monday instead of triggering a same-week round trip.
- **Exit hysteresis** — you *enter* on the strict screen (chg 1M > 5%, all the
  rules) but only *exit* when a name fails a looser hold test (chg 1M ≤
  `HOLD_CHG_FLOOR`, default 0) for `EXIT_GRACE_DAYS` days running (default 3). A
  one-day dip doesn't knock anything out; genuine deterioration does. Risk exits
  can still fire on any day — only new entries wait for the rebalance.
- **Liquidity filter** — drop anything below `MIN_DOLLAR_VOLUME` average daily
  dollar volume (default $5M) so your own order can't move the price. Applied in
  the live screen and every Python path.
- **No forced rotation** — a full book doesn't evict a holder for a hotter name;
  holders leave only via the exit rule. Rotation is pure turnover.

Tune all of it with environment variables (see `daily_target.py`).

## Health momentum (a sector book)

A third strategy, **health only** — pharma, biotech, medical devices, digital
health, hospitals, and health insurers (managed care) — via TradingView's two
health sectors, "Health Technology" and "Health Services".

It's not the aggressive screen with a sector filter; health is different:
- **No profitability gate by default** — clinical-stage biotech is pre-revenue, so
  ROE>0 would delete exactly the biotech runners you want. `PROFIT_GATE=1` (engine)
  or `?quality=1` (web) re-enables it for a quality tilt.
- **Lower size floors** (price ≥ $5, cap ≥ $300M, ADV ≥ $3M) and slightly looser
  momentum thresholds, since health skews smaller and choppier.
- Same composite ranking; each name is tagged with its **sub-industry** (biotech,
  pharma, managed care, medical specialties…), and the dashboard shows the mix.

```bash
cd engine
RANK_METHOD=composite python health.py --dry-run     # health momentum leaders
PROFIT_GATE=1 python health.py --dry-run             # quality tilt (no pre-revenue biotech)
```

⚠️ **Biotech carries binary event risk.** FDA decisions and trial readouts can gap
a stock tens of percent overnight. Momentum assumes trends persist; biotech can
violate that in one session, and no moving-average exit protects against a gap.
This ranks leaders — it does not neutralize catalyst risk. Size down and diversify.
The dashboard's **Health** tab carries this warning inline. Own state
(`holdings_health.json`), so it paper-trades alongside the other two books.

**Balanced book** (a sub-view on every screen tab — Conservative, Aggressive,
Health). Instead of the top-N leaders — which can pile into one group — this builds
a diversified book: it groups the passing names and takes the single best large-cap
and single best small-cap in each group (by composite score). Conservative and
Aggressive group by **sector** (a book spanning the whole market); Health groups by
**sub-industry** (biotech, pharma, managed care…). Weighting is adjustable live: a
**conviction** slider (equal-weight to score-weighted), a **large/small tilt**, and a
cap-line preset ($2B / $5B / $10B). Math is in `src/components/portfolio.js` and
`BalancedBook.jsx` (pure, tested). Note: the Aggressive book skews large-cap because
its $20M-ADV liquidity gate filters out most genuinely small names, so "small" there
means mid/smaller-large. A group missing a tier contributes one name.

## Momentum visualizer (live, multi-timeframe)

The dashboard's **Momentum viz** tab shows, for the current picks of any book
(conservative / aggressive / health), how strong each name's momentum is and
whether it's building or fizzling — across 1W / 1M / 3M / 6M / 1Y.

Each TradingView `Perf.*` window is a trailing cumulative return over a different
length, so dividing each by its length gives a comparable **per-month rate**. The
sparkline plots that rate oldest->newest (1Y left, 1W right): rising to the right =
**accelerating**, falling = **fading**, dropping below zero on the right =
**reversing**. Each name gets a state badge, a 0-100 strength meter (ADX blended
with how many windows are still positive), an acceleration number (points/month),
and a **fizzling** flag that fires when the recent pace has turned down and price
has slipped below its 20-day line.

Math is in `api/_momentum.js` (pure, tested); `api/momentum.js` takes
`?symbols=EX:TICK,...` and the frontend feeds it the chosen book's live picks. It's
a smoothed read from trailing returns, not a tick feed — the *shape* is the signal.

## Backtest (price-proxy + significance)

The **Backtest** tab runs an event-driven backtest of the price-based composite
signal — the part that *can* be tested without point-in-time data. It does NOT
replay the fundamental/ratings screen (that needs survivorship-free history we
can't get; a survivor-only version would be badly upward-biased). Mechanics: signal
on the rebalance close, fills at the next open (no lookahead), transaction + slippage
cost on traded notional, monthly rebalance, marked to close. Two modes: `strategy`
(hold top-N) and `signal` (long top-decile). Benchmarked against SPY.

Crucially it ships the **significance layer** the validation research demanded, so a
lucky curve can't pass for edge:
- **Probabilistic Sharpe** — prob. the true Sharpe beats 0 given sample length, skew, kurtosis.
- **Deflated Sharpe** — the same, but against the expected-best Sharpe from the N
  variants already tried; a high CAGR with a low deflated Sharpe is probably luck.
- **Min track record** — how many years you'd need before the Sharpe is statistically real.

Math is in `engine/backtest_stats.py` and `engine/backtest.py` (pure, tested).

```bash
python engine/backtest.py --sample                    # synthetic demo (no network)
python engine/backtest.py --start 2015-01-01          # live via yfinance (DEMO_UNIVERSE)
python engine/backtest.py --tickers universe.txt --mode signal
```

⚠️ A backtest on a fixed CURRENT ticker list is survivorship-biased. Even a clean
run is in-sample and overstates live results — read the deflated Sharpe and min
track record, not the CAGR. This is a sanity check on the engine, not proof of edge;
only the forward paper record settles that.

## Filter stability (sensitivity harness)

Answers "are these the best thresholds?" the honest way — by showing whether they
even *matter*. `engine/sensitivity.py` slides each aggressive gate across a range
(holding the others fixed) and measures how much the survivor set changes (Jaccard
overlap with baseline). A knob whose overlap stays high is robust — the exact
number doesn't matter. A knob whose overlap collapses is load-bearing and an
overfitting suspect. It measures set *stability* on live data, not returns — it
can't tell you a threshold is profitable, only whether the screen is sensitive to it.

```bash
python engine/sensitivity.py           # live scan -> public/sensitivity.json
python engine/sensitivity.py --sample  # demo data, no network
```

The dashboard's **Filter stability** tab renders it: per-knob overlap bars with a
robust / load-bearing badge. Refreshed by `.github/workflows/sensitivity.yml`.

## Momentum age & screen tenure

Two reads of "how long has it had momentum," on the dashboard's **Momentum age** tab:

- **Trend age** (from price, available now): consecutive days each survivor has
  closed above its 50- and 200-day moving averages, plus the share of the last 6
  months above the 50-day. `engine/momentum_age.py` computes it from daily bars
  (yfinance). Above the 200-day for 300 days = a year-plus run; above the 50-day
  for 5 days = a fresh breakout.
- **Screen tenure** (from our own log, accrues): `snapshot.py` tracks a per-ticker
  streak of how many consecutive snapshot runs a name has stayed in the screen,
  in `public/snapshots/tenure.json`.

```bash
python engine/momentum_age.py           # live -> public/momentum_age.json
python engine/momentum_age.py --sample  # demo, no network
```

Longer isn't automatically better — extended moves are more reversal-prone, so the
tab flags late-stage names (amber) rather than endorsing them. Trend age is exact
immediately; screen tenure only counts observed days, so it understates true tenure
early on. Refreshed weekly by `.github/workflows/momentum-age.yml`.

## What's next: validation (needs a forward record)

Whether this actually makes money can't be a dashboard widget yet — the honest
tools (deflated Sharpe, Carhart factor attribution, PBO, minimum track-record
length) need a real forward record. Those become panels once the Alpaca paper race
has run for months. Short version from the research brief: paper-trade prospectively,
benchmark against SPY / RSP / MTUM, and correct for the many variants already tried
before believing any Sharpe.

## Run the website

```bash
npm install && npm i -g vercel
vercel dev        # localhost:3000 — serves the site AND /api/screen
```

Use `vercel dev`, not `vite dev` (plain Vite won't serve `api/`). Deploy: push to
GitHub → import on Vercel → deploy. Zero config; the screen runs live on each load.

## Where this sits on the road to "live"

Rung 1 (this) = alerts, no execution. Next rungs, in order: **paper trade**
through a broker API (Alpaca's paper account is identical to live), then tiny
live with hard guardrails (position cap, daily-loss kill switch, broker-vs-target
reconciliation). Don't skip rungs — that's how a screen bug becomes a 2am
liquidation.

---

Not investment advice. A stock passing the screen is a hypothesis, not a
recommendation. Paper-trade the sheet for weeks before any real capital — most
automated retail strategies lose to a plain index fund after costs and mistakes.
