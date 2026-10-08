# Final Unified Head-to-Head Verdict — 2026-09-02

## Decision

- **Historical risk-adjusted leader:** `BALANCED_TREND_V2F`
- **Current REAL / Production decision:** keep `BALANCED_TREND_V1`
- **v2 status:** strong SHADOW / champion challenger; do **not** promote from this retrospective test alone
- **Passive comparator:** `STATIC_30_30_15_15_10` has the highest primary CAGR but materially larger drawdown
- **PQ role:** `PQ_CORE_60_40_214980_V1` remains a simple Korean-beta defensive benchmark/core, not the unified risk-adjusted winner

## Evidence identity

Successful public workflow:

- repository: `masonbcshin/KR-security-test`
- branch: `research/final-unified-head-to-head-20260902`
- run: `33614736138`
- artifact: `9840461934` (`final-unified-head-to-head`)
- commit: `3df7a00ca0dafa1a258b2145c952c8a7410fc258`

Authoritative PQ market-split source:

- prior run: `32492902475`
- artifact: `9450776179`
- source: `cadence_84d/signals.csv`
- exact historical market-split weights were replayed; no fixed split was invented

## Common test

- evaluation: `2018-01-02` through `2026-03-20`
- warm-up: starts 2016
- primary execution: month-end / rebalance signal then T+1 adjusted close
- execution stress: T+1 adjusted open
- primary friction: 11.5bp per traded notional
- friction stress: 25bp, 50bp
- prices: common Yahoo adjusted total-return panel
- tax panel: separate 15.4% conservative positive-realized-gain proxy for taxable ETF sleeves; this is intentionally conservative and is **not** statutory historical 과표기준가 accounting

## Primary apples-to-apples result

| Rank | Strategy | CAGR | Sharpe | MDD | Calmar | Annual turnover | DSR (8 trials) |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | `BALANCED_TREND_V2F` | **9.29%** | **1.101** | **-8.03%** | **1.157** | 3.261x | **0.942** |
| 2 | `BALANCED_TREND_V1` | 9.18% | 1.065 | -8.41% | 1.093 | 3.225x | 0.930 |
| 3 | `STATIC_30_30_15_15_10` | **10.83%** | 0.921 | -22.16% | 0.488 | 0.325x | 0.866 |
| 4 | `PQ_CORE_60_40_214980_V1` | 9.12% | 0.753 | -26.07% | 0.350 | **0.136x** | 0.739 |

The static allocation wins on raw CAGR, but v1/v2 dominate on drawdown and risk-adjusted return. PQ obtains roughly the same CAGR as v1/v2 in this common sample but with about 3x the maximum drawdown and materially lower Sharpe.

## Rolling-return stress

| Strategy | Worst rolling 1y | Worst rolling 3y annualized | Worst rolling 5y annualized |
|---|---:|---:|---:|
| `BALANCED_TREND_V2F` | **-5.78%** | +0.19% | +3.11% |
| `BALANCED_TREND_V1` | -6.23% | **+0.34%** | +3.02% |
| `STATIC_30_30_15_15_10` | -18.43% | +0.98% | **+3.73%** |
| `PQ_CORE_60_40_214980_V1` | -18.78% | **-2.71%** | +0.83% |

## Subperiod stability

Primary test results:

- v2: 2018-2021 CAGR 6.64%, Sharpe 0.921; 2022-latest CAGR 11.90%, Sharpe 1.250
- v1: 2018-2021 CAGR 6.54%, Sharpe 0.875; 2022-latest CAGR 11.79%, Sharpe 1.221
- static: 2018-2021 CAGR 8.84%, Sharpe 0.819; 2022-latest CAGR 12.77%, Sharpe 1.010
- PQ: 2018-2021 CAGR 4.60%, Sharpe 0.459; 2022-latest CAGR 13.65%, Sharpe 0.987

PQ is the most regime-dependent of the four in risk-adjusted terms. v1/v2 are substantially more stable across the two broad subperiods.

## Bootstrap / overfitting diagnostics

CSCV across the four aligned daily return series:

- **PBO = 24.29%**
- 70 CSCV combinations
- median OOS-rank logit = +0.405

Paired 21-trading-day block bootstrap (2,000 resamples):

- P[Sharpe(v2) > Sharpe(v1)] = **88.85%**
- P[Sharpe(v2) > Sharpe(static)] = **73.95%**
- P[Sharpe(v2) > Sharpe(PQ)] = **92.00%**
- P[Sharpe(v1) > Sharpe(static)] = **69.25%**
- P[Sharpe(v1) > Sharpe(PQ)] = **88.70%**

Interpretation: v2 is the historical leader, but its edge over v1 is not overwhelming enough to treat the two as definitively separated future distributions. The DSR of 0.942 is also slightly below a stringent 0.95 threshold, while PBO remains non-zero and material. This supports keeping v1 as the production champion while collecting genuine forward evidence for v2.

## Cost / execution / tax robustness

v2 remained Sharpe rank #1 in **10 of 12** execution-cost-tax scenarios and rank #2 in the two harshest combinations (50bp plus conservative tax proxy). It remained top-2 in every scenario and its worst scenario MDD was about -12.7%, satisfying the frozen robustness rule.

At 50bp + conservative tax proxy, static becomes Sharpe #1 because its turnover is far lower:

- next-close: static Sharpe 0.887, v2 0.874, v1 0.843, PQ 0.747
- next-open: static Sharpe 0.889, v2 0.864, v1 0.836, PQ 0.751

At the production-like primary 11.5bp + conservative tax proxy, v2 remains #1:

- v2 CAGR 8.62%, Sharpe 1.029, MDD -9.72%
- v1 CAGR 8.51%, Sharpe 0.993, MDD -10.09%
- static CAGR 10.52%, Sharpe 0.898, MDD -22.19%
- PQ CAGR 9.10%, Sharpe 0.751, MDD -26.08%

The tax proxy is a stress test only; final Korean general-account after-tax ordering needs historical 과표기준가 if statutory precision is required.

## Final adjudication

### `BALANCED_TREND_V1` — KEEP / REAL

Keep as the current production strategy. It captures almost all of v2's historical risk-adjusted benefit with a simpler frozen rule and already holds the production status.

### `BALANCED_TREND_V2F` — HISTORICAL WINNER / SHADOW

The unified historical tournament strengthens v2 materially: it wins primary Sharpe, MDD and Calmar, and is top-2 in all 12 robustness scenarios. Nevertheless this is retrospective evidence that overlaps strategy development history. It does not erase the previously frozen promotion failure. Continue genuine forward SHADOW validation.

### `STATIC_30_30_15_15_10` — KEEP AS BENCHMARK / RETURN-ORIENTED ALTERNATIVE

It has the highest raw CAGR and exceptionally low turnover. It becomes attractive when friction/tax is assumed extremely high, but its MDD is ~-22%, versus ~-8% for v1/v2, so it is not the preferred risk-controlled personal-quant automation strategy.

### `PQ_CORE_60_40_214980_V1` — KEEP AS PASSIVE CORE / FALLBACK BENCHMARK

It is simple and low-turnover, but the common test does not support it as the best overall personal-quant strategy. Its Sharpe is lowest and MDD is ~-26% despite CAGR close to v1/v2.

## What would change the production decision?

Do not tune more historical parameters. Keep v1 REAL and v2 SHADOW. Re-adjudicate only after genuine forward observations accumulate under the frozen v2 rule. The next evidence should come from PAPER/SHADOW live signals, not another retrospective SMA-grid search.
