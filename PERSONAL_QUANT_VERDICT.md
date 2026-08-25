# Personal-Quant Production Baseline Verdict — 2026-08-21

## Current decision

For an individual Korean quant, the preferred Korean-equity baseline is:

> **KODEX 코스피 (226490) + KODEX 코스닥150 (229200), dynamically weighted by the eligible research universe's KOSPI/KOSDAQ market-cap split, with target weights refreshed every 84 trading days and executed T+1.**

This is a benchmark-translation baseline, not a claimed alpha strategy.

The composition and the cadence were validated in two separate pre-registered stages:

1. ETF proxy tournament: choose an investable translation of the winning fractional full-cap research benchmark.
2. Cadence robustness test: test 21 / 42 / 63 / 84 trading-day target-weight refreshes without changing ETF composition or market-split logic.

The earlier KRW 100m + Top-50 stock basket remains a stock-only comparator, but the two-ETF implementation is preferred because it works at KRW 10m / 30m / 100m with drastically lower operational burden.

No tested active factor strategy is promoted.

## Stage 1 — ETF proxy selection

Pre-registration: PR #1 comment `5364956891`.

Authoritative run: `32444932528`.
Artifact: `kr-personal-quant-etf-proxy`, ID `9433892498`, digest `sha256:d8fc35d73cba12788e7ae41e91d2ceffeaf092d4d10ae3ca12639b60268a74f2`.

Machine-readable results:

- `results/2026-08-21-etf-proxy-performance.csv`
- `results/2026-08-21-etf-proxy-capital.csv`

The four frozen candidates were KODEX KOSPI, KODEX 200, KODEX KOSPI + KODEX KOSDAQ150 dynamic split, and KODEX 200 + KODEX KOSDAQ150 dynamic split.

Only the KODEX KOSPI + KODEX KOSDAQ150 dynamic split passed every frozen benchmark-translation performance gate.

| Candidate | CAGR | Sharpe | MDD | Tracking error | Result |
|---|---:|---:|---:|---:|---|
| KODEX KOSPI | 12.92% | 0.717 | -41.27% | 4.10% | FAIL — CAGR/Sharpe drift |
| KODEX 200 | 14.70% | 0.761 | -38.09% | 4.28% | FAIL — CAGR/Sharpe drift |
| **KODEX KOSPI + KOSDAQ150 split** | **12.09%** | **0.671** | **-43.24%** | **3.66%** | **PASS** |
| KODEX 200 + KOSDAQ150 split | 13.75% | 0.718 | -40.48% | 3.48% | FAIL — CAGR/Sharpe drift |

The selected proxy was deliberately not chosen by highest historical return.

The authoritative fractional full-cap reference reproduced at:

- CAGR 10.695381%
- Sharpe 0.599321
- MDD -40.968565%

The ETF proxy full runner and an independent price-snapshot replay matched the accepted metrics to floating-point tolerance.

## Dynamic allocation rule

The portfolio is not a fixed 90/10 allocation.

At each scheduled target-weight refresh date:

1. rebuild the same eligible stock universe used by the benchmark;
2. aggregate eligible market capitalization separately for KOSPI and KOSDAQ;
3. KODEX KOSPI weight = KOSPI eligible market cap / total eligible market cap;
4. KODEX KOSDAQ150 weight = KOSDAQ eligible market cap / total eligible market cap;
5. execute the target change on T+1.

In the original 42-day ETF-selection run, the KOSPI weight averaged about 89.9% and ranged roughly 86.0% to 93.6%. Those values are historical observations, not a fixed production allocation.

## Stage 2 — rebalance-cadence robustness

The initial 42-day cadence was inherited from the stock tournament; it was not previously proven to be an optimal ETF refresh interval.

Pre-registration: PR #1 comment `5371279681`.

Frozen cadence candidates:

- 21 trading days
- 42 trading days
- 63 trading days
- 84 trading days

No extra cadence was added after results were observed.

Authoritative run: `32492902475`.
Artifact: `kr-etf-rebalance-robustness`, ID `9450776179`, digest `sha256:52214865895e1b1a610e321ab7eadc345fa67fd638e90c7192b5393cdbc4b145`.

Persistent verdict: `ETF_REBALANCE_ROBUSTNESS_VERDICT.md`.
Machine-readable results:

- `results/2026-08-21-etf-rebalance-robustness.csv`
- `results/2026-08-21-etf-rebalance-subperiods.csv`

| ETF refresh | Rebalances | CAGR | Sharpe | MDD | Calmar | TE | Tx/year | Cost (KRW 100m convention) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 21d | 96 | 12.048% | 0.6691 | -43.330% | 0.2780 | 3.665% | 23.39 | 2.199m |
| 42d | 48 | 12.094% | 0.6712 | -43.238% | 0.2797 | 3.663% | 11.70 | 2.030m |
| 63d | 32 | 12.104% | 0.6716 | -43.334% | 0.2793 | 3.663% | 7.80 | 1.945m |
| **84d** | **24** | **12.107%** | **0.6715** | **-43.354%** | **0.2792** | **3.663%** | **5.85** | **1.907m** |

All four cadences passed the same fidelity gates and all four fell inside the pre-registered Sharpe/Calmar performance plateau.

Subperiod Sharpe was likewise almost invariant:

| Cadence | 2018–2021 | 2022–2024 | 2025–2026-03 |
|---|---:|---:|---:|
| 21d | 0.4018 | -0.2366 | 2.6933 |
| 42d | 0.4029 | -0.2327 | 2.6949 |
| 63d | 0.4030 | -0.2314 | 2.6948 |
| 84d | 0.4017 | -0.2308 | 2.6970 |

Therefore the cadence finding is primarily **robustness**, not a narrow optimum. The ETF proxy historically works almost the same anywhere from roughly one to four months.

The frozen operational tie-break selected **84 trading days** because it preserves the same risk-adjusted performance plateau while reducing implementation burden.

Versus 42 days, 84 days produced:

- 50% fewer transactions/year;
- about 17.3% lower gross turnover/year;
- about 6.1% lower modeled transaction cost;
- essentially unchanged Sharpe, MDD, Calmar, and tracking error.

Do not now search 70/75/80/90/100-day cadences on the same history. That would turn the robustness test into cadence overfitting.

## Whole-share feasibility

The original ETF tournament demonstrated whole-share feasibility at KRW 10m / 30m / 100m under the 42-day snapshots.

A post-selection operational check on the 24 historical 84-day signal snapshots also retained feasibility:

| Capital | Avg residual cash | Max residual cash | Instruments achieved |
|---:|---:|---:|---:|
| KRW 10m | 0.199% | 0.391% | 2 / 2 at every snapshot |
| KRW 30m | 0.059% | 0.117% | 2 / 2 at every snapshot |
| KRW 100m | 0.0179% | 0.0416% | 2 / 2 at every snapshot |

This post-selection lot check is operational validation, not a performance-selection input.

## Current personal-quant hierarchy

1. **Preferred baseline:** KODEX KOSPI + KODEX KOSDAQ150 dynamic eligible-market-cap split, **84 trading-day refresh**
2. **Stock-only fallback / research comparator:** KRW 100m + Top-50 eligible stocks, cap-weighted
3. **Best tested active strategy:** Long-Reversal — research-only, not promoted
4. KR-CORE and other tested active models — rejected under the existing tournament

## What is and is not proven

Supported by the retrospective/pseudo-OOS framework:

- the two-ETF proxy tracks the winning full-cap research benchmark within every frozen performance gate;
- whole-share implementation is feasible at all tested capital tiers;
- changing the ETF refresh cadence between 21 and 84 trading days barely changes historical performance;
- 84 days is the lowest-burden choice under the pre-registered plateau rule.

Not proven:

- genuinely untouched forward OOS alpha;
- that 84 days is globally optimal;
- that live slippage/tax outcomes exactly equal the conservative research cost assumptions;
- that historical target weights should be used today without rebuilding current data.

## Production status

Baseline selection and cadence sensitivity are now complete enough to stop historical cadence searching.

Production should use the **84-trading-day schedule**, but automatic live orders remain blocked until the current data pipeline passes freshness checks. The latest audit found market data close to current while PIT financial availability was stale, so DART/PIT freshness must be repaired before `LIVE_READY=true` is permitted.
