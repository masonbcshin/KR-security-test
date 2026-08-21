# Personal-Quant Baseline Translation Verdict — 2026-08-21

## Decision

The fractional full-eligible-universe `universe_cap` research winner is **not directly executable at typical small personal-account capital**.

Under the pre-registered translation matrix, only one stock-basket cell passed every fidelity and lot-feasibility gate:

- **KRW 100m + Top 50 market-cap-weighted basket**

KRW 10m and KRW 30m produced no passing stock-basket translation.

This is an **investable stock-baseline candidate**, not yet a production recommendation. Historical return tracking and whole-share feasibility were deliberately separated because the research database uses backward-adjusted prices for return continuity; such adjusted prices are invalid for historical whole-share sizing around splits and similar corporate actions.

Authoritative run: GitHub Actions `32437739907`, artifact `kr-personal-quant-baseline`, artifact ID `9431546210`, digest `sha256:e93792926c0b4471d41a5a7c64653795bb2296df98cf2b976290780e06468256`.

Machine-readable result: `results/2026-08-21-personal-quant-baseline.csv`.

## Pre-registered methodology

PR #1 comments `5364180007` and `5364210629` fixed the experiment before results were inspected.

Matrix:

- capital: KRW 10m / 30m / 100m
- breadth: Top 20 / 50 / 100 eligible stocks by signal-date market cap
- weighting: market-cap weight within the selected Top-N
- same common tournament universe
- 42-trading-day rebalance
- T+1 execution
- buy cost 0.35%, sell cost 0.55%
- no factor, threshold, rank, timing, leverage, or holding-period tuning

Historical Top-N tracking is simulated fractionally against the authoritative full-universe fractional cap benchmark. Whole-share feasibility is measured separately at each rebalance with actual raw `daily_prices.closing_price` on T+1 and whole-share floor sizing after reserving buy cost.

A capital/N cell passes only if both components pass.

Fidelity gates:

- annualized tracking error <= 5.0%
- absolute CAGR gap <= 1.5 percentage points
- absolute Sharpe gap <= 0.10
- absolute MDD gap <= 5 percentage points
- average residual cash <= 5%
- maximum residual cash <= 15%
- average achieved position count >= 90% of target N

## Reference reproduction

The newly generated full-universe fractional reference reproduced the existing authoritative benchmark exactly at the guarded metrics:

- CAGR: 10.695381%
- Sharpe: 0.599321
- MDD: -40.968565%

Validation differences versus the persisted authoritative values were exactly `0.0` for all three metrics.

## Historical Top-N tracking

| Basket | CAGR | Sharpe | MDD | Tracking error | CAGR gap | Historical gate |
|---|---:|---:|---:|---:|---:|---|
| Top 20 | 13.39% | 0.665 | -38.95% | 5.96% | +2.69pp | **FAIL** |
| Top 50 | 12.14% | 0.641 | -37.06% | 3.41% | +1.45pp | **PASS** |
| Top 100 | 11.65% | 0.633 | -38.66% | 2.06% | +0.95pp | **PASS** |

Top 20 is rejected as a benchmark translation despite its higher historical return because it fails the pre-registered tracking-error and CAGR-gap gates. The experiment does not reward accidental historical outperformance when the objective is benchmark translation.

Subperiod Sharpe:

| Period | Full cap | Top 50 | Top 100 |
|---|---:|---:|---:|
| 2018–2021 | 0.386 | 0.398 | 0.391 |
| 2022–2024 | -0.398 | -0.369 | -0.369 |
| 2025–2026-03 | 2.636 | 2.702 | 2.685 |

Top 50 and Top 100 preserve the broad regime behavior of the reference reasonably well under the registered tracking gates.

## Raw-price whole-share feasibility

### KRW 10m

No basket is feasible under the registered cash/fill gates.

- Top 20: average cash 26.87%, max cash 41.15%, average position fill 65.4%
- Top 50: average cash 39.16%, max cash 46.64%, average fill 43.0%
- Top 100: average cash 46.28%, max cash 53.98%, average fill 27.0%

### KRW 30m

No basket passes.

- Top 20: average cash 9.74%, max 17.77%, average fill 94.2%; lot feasibility improves, but Top 20 already fails historical tracking
- Top 50: average cash 16.60%, max 26.47%, average fill 82.0%
- Top 100: average cash 22.59%, max 31.55%, average fill 64.0%

### KRW 100m

- Top 20: lot gates pass, but historical tracking fails
- **Top 50: all gates pass**
- Top 100: historical tracking passes, but average cash 7.43% exceeds the 5% gate

Top 50 / KRW 100m raw-price lot statistics:

- average residual cash: **4.87%**
- maximum residual cash: **9.50%**
- average achieved positions: **49.54 / 50**
- minimum achieved positions: **46 / 50**
- average position fill: **99.08%**
- minimum position fill: **92%**
- missing/untradable target observations: **0**

The worst cash snapshot occurred at the 2026-01-19 signal / 2026-01-20 execution: 46 of 50 names were affordable and residual cash was 9.50%.

## Operational interpretation

The Top 50 historical basket generated about 311 transactions per year in the fractional tracking simulation, with gross turnover around 0.38x average equity per year. This is automatable but materially more operationally complex than a one- or two-ETF baseline.

Concentration also remains meaningful: the maximum single-name target weight observed in the Top 50 lot snapshots was about 38.5%. This does not retroactively fail the pre-registered experiment, because no concentration cap was registered. It is an operational/risk flag for later deployment comparison.

## Important limitation

The passing Top 50 / KRW 100m cell does **not** yet constitute a full path-dependent historical whole-share backtest.

Reason:

- adjusted prices are required for clean return continuity through splits and similar corporate actions;
- raw prices are required to know how many whole shares an investor could actually buy at each historical execution date;
- naïvely using the backward-adjusted price for lot sizing materially understates historical per-share cash requirements.

Therefore this phase proves two separate things:

1. Top 50 historically tracks the research winner closely enough under the registered fidelity gates; and
2. KRW 100m is sufficient to form those Top 50 target weights with raw T+1 prices under the registered lot gates.

It does not yet prove an exact path-dependent whole-share P&L series after every corporate action.

## Current personal-quant status

- KRW 10m stock-basket cap translation: **REJECT**
- KRW 30m stock-basket cap translation: **REJECT**
- KRW 100m Top 20: **REJECT** — tracking fidelity
- KRW 100m Top 50: **PASS AS STOCK-BASELINE CANDIDATE**
- KRW 100m Top 100: **REJECT** — residual cash gate

## Next phase

Do not optimize Top-N further on this history.

The next phase is a separately pre-registered **ETF / index-proxy baseline tournament**. Its purpose is to determine whether a much simpler one- or two-ETF implementation can provide a better personal-quant baseline, especially for KRW 10m and KRW 30m where direct stock baskets failed.

Candidate building blocks must have live history covering the test window and must be fixed before their comparative result is inspected. Initial public-product candidates include broad KOSPI and KOSDAQ index ETFs; exact symbols, data availability, blend rule, dividend treatment, costs, and rebalance rule must be audited and registered before execution.
