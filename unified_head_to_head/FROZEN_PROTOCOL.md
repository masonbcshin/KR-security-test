# Final Unified Head-to-Head — Frozen Protocol

Frozen before observing results on 2026-09-02.

## Strategies
1. `PQ_CORE_60_40_214980_V1`
   - 60% equity sleeve: `226490` KODEX KOSPI + `229200` KODEX KOSDAQ150.
   - Equity sleeve split is recalculated from historical KOSPI total market cap versus KOSDAQ150 constituent market cap.
   - 40% `214980` KODEX 단기채권PLUS.
   - refresh every 84 KRX trading days, execute T+1.
2. `STATIC_30_30_15_15_10`
   - 30/30/15/15/10 in 069500/143850/148070/132030/153130.
3. `BALANCED_TREND_V1`
   - same base weights; 200-day SMA binary ON/OFF per risk asset; OFF weight to 153130.
   - month-end close signal, T+1.
4. `BALANCED_TREND_V2F`
   - same base weights; equal-vote 160/180/200/220/240-day SMA grid; 20% exposure increments.
   - month-end close signal, T+1.

## Common historical window
- Evaluation starts 2018-01-02.
- Warm-up starts 2016-01-01.
- End is the latest date common to every required ETF price series at execution time.
- This is retrospective / pseudo-OOS evidence, never genuine untouched forward OOS.

## Common data and execution
- Yahoo Finance adjusted total-return close and adjustment-factor-derived open proxy for every ETF.
- Primary execution: T+1 adjusted close.
- Execution stress: T+1 adjusted open.
- All strategies are marked to market on the same common trading calendar.

## Costs
- Primary: 11.5bp per traded notional (1.5bp commission + 10bp slippage, matching current production evidence assumptions).
- Stress: 25bp and 50bp per traded notional.

## Tax treatment
Two panels are mandatory:
1. pre-tax adjusted-total-return panel, used as the clean cross-strategy market/friction comparison;
2. identical conservative tax stress: 15.4% on positive realized gains for ETFs treated as taxable in a general Korean account (`143850`, `148070`, `132030`, `153130`, `214980`).

The tax stress is deliberately conservative and is NOT claimed to reproduce statutory ETF tax-base-price accounting, because Yahoo price history does not contain historical 과표기준가. A strategy may not be declared robust if its conclusion depends only on this approximate tax layer.

## Mandatory metrics
- CAGR, annual volatility, Sharpe, Sortino, MDD, Calmar
- annual turnover and cost/tax drag
- worst/positive rolling 1y, 3y, 5y
- 2018-2021 and 2022-latest subperiods
- calendar-year returns
- Deflated Sharpe Ratio using 8 visible historical trials as a conservative research-family count
- CSCV/PBO on aligned daily returns
- paired 21-trading-day block bootstrap for pairwise Sharpe superiority

## Ranking and promotion discipline
- Primary ranking: after-cost Sharpe, then Calmar/MDD, then CAGR and subperiod stability.
- Highest CAGR alone never wins.
- Robustness requires the primary leader to remain top-2 by Sharpe across every execution/cost/tax scenario and to avoid MDD worse than -30% across those scenarios.
- Most importantly: this retrospective tournament cannot retroactively relax the already frozen v2 promotion gate. Even if v2 ranks first historically, `BALANCED_TREND_V2F` remains SHADOW until genuine future/forward observations satisfy the existing preregistered promotion rule.
- No parameter may be changed after results are observed.
