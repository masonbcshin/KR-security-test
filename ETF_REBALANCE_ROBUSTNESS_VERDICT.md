# ETF Rebalance-Cadence Robustness Verdict — 2026-08-21

## Decision

For the promoted personal-quant ETF proxy (`KODEX KOSPI 226490 + KODEX KOSDAQ150 229200`, eligible-universe KOSPI/KOSDAQ market-cap split), the previously inherited **42-trading-day** refresh cadence is **not uniquely supported by the data**.

A pre-registered sensitivity test of **21 / 42 / 63 / 84 trading days** found all four cadences inside the same broad performance plateau and all four retained the previously registered benchmark-translation fidelity gates.

Under the pre-registered selection rule — fidelity -> subperiod stability -> broad Sharpe/Calmar plateau -> lowest operational burden — the selected implementation cadence is:

- **84 trading days**

This is a **same-history robustness/sensitivity result, not independent OOS validation**. It supports simplifying the implementation; it does not prove that 84 is a globally optimal rebalance interval.

Authoritative GitHub Actions run: `32492902475`.
Artifact: `kr-etf-rebalance-robustness`, artifact ID `9450776179`, digest `sha256:52214865895e1b1a610e321ab7eadc345fa67fd638e90c7192b5393cdbc4b145`.
Pre-registration: PR #1 comment `5371279681`.

Machine-readable results:

- `results/2026-08-21-etf-rebalance-robustness.csv`
- `results/2026-08-21-etf-rebalance-subperiods.csv`

## Frozen experiment

Only the ETF target-weight refresh cadence changed.

Unchanged:

- KODEX KOSPI (`226490`) + KODEX KOSDAQ150 (`229200`)
- target weights = signal-date eligible-universe KOSPI/KOSDAQ aggregate market-cap shares
- authoritative common universe and PIT/filter logic
- T+1 execution
- buy cost 0.35%, sell cost 0.55%
- no leverage, timing, stops, volatility targeting, static-weight optimization, or alpha changes
- authoritative fractional full-cap benchmark remains on its original 42-trading-day rule

Tested ETF refresh cadences were fixed before the new results were observed:

- 21 trading days
- 42 trading days
- 63 trading days
- 84 trading days

No other cadence was added after observing results.

## Full-period results: 2018-01-01 to 2026-03-20

| Cadence | Rebalances | CAGR | Sharpe | MDD | Calmar | Tracking error | Tx/year | Modeled cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 21d | 96 | 12.048% | 0.6691 | -43.330% | 0.2780 | 3.665% | 23.39 | KRW 2.199m |
| 42d | 48 | 12.094% | 0.6712 | -43.238% | **0.2797** | 3.663% | 11.70 | KRW 2.030m |
| 63d | 32 | 12.104% | **0.6716** | -43.334% | 0.2793 | 3.663% | 7.80 | KRW 1.945m |
| **84d** | **24** | **12.107%** | **0.6715** | **-43.354%** | **0.2792** | **3.663%** | **5.85** | **KRW 1.907m** |

All four pass the frozen fidelity gates against the authoritative fractional full-cap benchmark:

- tracking error <= 5%
- absolute CAGR gap <= 1.5pp
- absolute Sharpe gap <= 0.10
- absolute MDD gap <= 5pp

The accepted historical 42-day ETF baseline was reproduced before selection:

- CAGR difference: `0.0`
- Sharpe difference: `0.0`
- MDD difference: `0.0`
- tracking-error difference: `6.25e-17`

Therefore the sensitivity run is using the same implementation as the accepted ETF baseline.

## Subperiod stability

| Cadence | 2018-2021 Sharpe | 2022-2024 Sharpe | 2025-2026-03 Sharpe |
|---|---:|---:|---:|
| 21d | 0.4018 | -0.2366 | 2.6933 |
| 42d | 0.4029 | -0.2327 | 2.6949 |
| 63d | **0.4030** | -0.2314 | 2.6948 |
| 84d | 0.4017 | **-0.2308** | **2.6970** |

No cadence was worse than the 42-day baseline by more than 0.15 Sharpe in even one frozen subperiod. All passed the pre-registered subperiod-stability rule.

## Why 84 days is selected instead of 63 days

63 days has the numerically highest full-period Sharpe (`0.671576`), but the difference versus 84 days (`0.671471`) is only about `0.000105`.

The pre-registration explicitly prohibited selecting the single highest in-sample Sharpe when several schedules lie on the same performance plateau.

All four cadences satisfy the frozen plateau rule:

- Sharpe within 0.03 of the best eligible Sharpe
- Calmar within 10% of the best eligible Calmar

The operational tie-break therefore controls the decision.

Compared with 42 days, 84 days produces:

- **50% fewer transactions/year**: 11.70 -> 5.85
- **17.3% lower gross turnover/year**: 0.1741x -> 0.1440x average equity
- **6.1% lower modeled transaction cost**: KRW 2.030m -> KRW 1.907m on the KRW 100m research convention
- essentially unchanged Sharpe, MDD, Calmar, and tracking error

Compared with 21 days, 84 days reduces transaction frequency by 75% while slightly improving the tested full-period risk-adjusted metrics.

## Interpretation

The main finding is not that `84` is a magical optimum. The stronger finding is that the ETF proxy is **very insensitive to rebalance cadence across roughly one to four months**.

That is desirable for a personal-quant baseline because it means the strategy does not depend on hitting a narrow rebalance frequency to work historically.

The evidence supports replacing the inherited 42-day implementation cadence with **84 trading days** for the current production baseline because the tested performance is effectively unchanged while operational burden falls materially.

Do not now search 70, 75, 80, 90, 100, etc. on the same 2018-2026 history. That would convert this robustness test into cadence overfitting.

## Current production baseline specification

- instruments: KODEX KOSPI (`226490`) + KODEX KOSDAQ150 (`229200`)
- target weights: eligible-universe KOSPI/KOSDAQ aggregate market-cap share
- target-weight refresh: **every 84 trading days**
- execution: T+1
- costs for research comparison: buy 0.35%, sell 0.55%
- suitable tested capital tiers: KRW 10m / 30m / 100m
- status: baseline implementation candidate; live automation remains blocked until production data-freshness requirements, especially PIT financial freshness, are satisfied
