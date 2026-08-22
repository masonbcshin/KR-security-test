# ETF Fixed Risk-Budget Verdict — 2026-08-22

## Decision

A separately pre-registered fixed-risk-budget study found that the accepted 84-trading-day two-ETF baseline can reduce historical drawdown below the production target without changing the ETF engine or adding a timing model.

The only candidate that passed every frozen production gate was:

> **60% equity / 40% cash target at each existing 84-trading-day refresh**

This is a **risk-budget candidate**, not a new alpha strategy and not a live-ready production rule yet. It still requires forward/paper confirmation. Cash was modeled at **0% return**, so no cash-product yield is credited to the backtest.

Pre-registration: PR #1 comment `5376827268`.
Authoritative reproduction run: `32541276654`.
Artifact: `kr-etf-fixed-risk-budget`, artifact ID `9467097129`, digest `sha256:2beee09a3612256085147296aa49ab5ff9c61d3224c620c319ee6f81438425f2`.
Machine-readable result: `results/2026-08-22-etf-fixed-risk-budget.csv`.

## Frozen experiment

Immutable underlying:

- KODEX KOSPI (`226490`) + KODEX KOSDAQ150 (`229200`)
- accepted eligible-universe KOSPI/KOSDAQ market-cap split
- accepted 84-trading-day signal dates
- T+1 execution
- buy cost 0.35%, sell cost 0.55%
- authoritative accepted artifact from run `32492902475`

Only one variable changed: fixed equity exposure.

Candidates frozen before result inspection:

- 100% equity / 0% cash
- 80% equity / 20% cash
- 70% equity / 30% cash
- 60% equity / 40% cash
- 50% equity / 50% cash

Residual cash earned 0%. The equity/cash target was reset only on existing 84-day refreshes; there was no daily rebalancing.

No trend filter, volatility target, leverage, stop, alternate cadence, dynamic cash yield, or additional exposure value was added after observing results.

## Primary result

| Equity | Cash | CAGR | Sharpe | MDD | Calmar | 2018-2024 Sharpe | All gates |
|---:|---:|---:|---:|---:|---:|---:|---|
| 100% | 0% | 12.11% | 0.6715 | -43.35% | 0.2792 | 0.1430 | FAIL — MDD |
| 80% | 20% | 10.01% | 0.6728 | -35.49% | 0.2820 | 0.1397 | FAIL — MDD |
| 70% | 30% | 8.90% | **0.6729** | -31.41% | 0.2834 | 0.1384 | FAIL — MDD |
| **60%** | **40%** | **7.75%** | **0.6726** | **-27.22%** | **0.2847** | **0.1372** | **PASS** |
| 50% | 50% | 6.56% | 0.6717 | **-22.94%** | **0.2860** | 0.1362 | FAIL — subperiod stability |

Frozen production gates:

1. historical MDD magnitude <= 30%
2. Sharpe >= baseline Sharpe - 0.03
3. Calmar >= baseline Calmar
4. CAGR >= 6.0%
5. 2018-2024 total return > 0 and Sharpe >= 0
6. no frozen subperiod Sharpe worse than baseline by >0.15
7. longest underwater not longer than baseline

The 60/40 candidate passed all seven. The 50/50 candidate failed only the frozen subperiod-stability gate because its 2025-2026 Sharpe fell by more than 0.15 versus the 100% equity baseline. The 70/30 candidate narrowly missed the primary drawdown goal with MDD -31.41%.

## What changed at 60/40

Compared with 100% equity:

- CAGR: **12.11% -> 7.75%**
- Sharpe: **0.6715 -> 0.6726**
- MDD: **-43.35% -> -27.22%**
- Calmar: **0.2792 -> 0.2847**
- modeled transaction cost: **KRW 1.907m -> KRW 1.212m** on the KRW 100m research convention
- gross traded: **KRW 388.7m -> KRW 250.2m**
- longest underwater: **969 -> 967 trading days** (effectively unchanged)

The main benefit is therefore **drawdown compression**, not Sharpe creation. The Sharpe ratio stays almost unchanged because fixed cash exposure mostly scales market risk and return together.

## Post-selection diagnostics

These diagnostics were not used to choose 60/40.

### Rolling annualized return for 60/40

| Window | Positive | Worst | 5th pct | Median | 95th pct |
|---|---:|---:|---:|---:|---:|
| 1y / 252d | 60.92% | -18.98% | -13.60% | **3.71%** | 37.59% |
| 3y / 756d | 77.60% | -3.71% | -2.22% | **4.83%** | 14.27% |
| 5y / 1260d | 99.87% | -0.04% | +1.29% | **4.11%** | 9.04% |

With 40% cash credited at 0%, a conservative planning return is therefore closer to **4-5% nominal/year** than the 7.75% full-history CAGR.

### 20,000-path 21d moving-block bootstrap for 60/40

Deterministic seed `20260822`.

- CAGR 5th percentile: **-0.06%**
- CAGR 25th percentile: **4.55%**
- CAGR median: **7.87%**
- probability ending loss over a full resampled horizon: **5.15%**
- median MDD: **-22.94%**
- severe 5th-percentile MDD: **-38.81%**
- P(MDD <= -30%): **20.26%**
- P(MDD <= -40%): **4.00%**
- P(MDD <= -50%): **0.55%**

Therefore the historical MDD gate does **not** imply a hard -30% loss ceiling. Sequence risk can still produce materially deeper drawdowns.

## Interpretation

The fixed 60/40 overlay answers the previous concern about excessive MDD more cleanly than the rejected 10-month trend overlay.

The trend overlay cut MDD to about -22.5%, but it failed its separately preregistered pre-2025 Sharpe-improvement gate and was locked as rejected; it must not be rescue-tuned on the same sample.

The 60/40 result is different: it does not claim timing skill. It simply fixes the portfolio's equity risk budget. That makes it easier to explain, automate, audit, and maintain.

## Current status

- **Underlying equity engine:** accepted 84d two-ETF dynamic market-cap split
- **Preferred fixed-risk-budget candidate:** 60% equity / 40% cash
- **Historical full-period metrics:** CAGR 7.75%, Sharpe 0.673, MDD -27.22%
- **Conservative planning return with zero-yield cash:** roughly 4-5% nominal/year
- **Live status:** not promoted directly; requires forward/paper confirmation and current-data freshness

Do not now test 55%, 65%, 75%, 85%, 90%, or alternate cash assumptions merely to improve the same-history result. That would turn a coarse risk-budget study into exposure overfitting.
