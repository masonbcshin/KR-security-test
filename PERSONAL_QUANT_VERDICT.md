# Personal-Quant Production Baseline Verdict — 2026-08-21

## Final decision

For an individual Korean quant, the preferred baseline is now:

> **KODEX 코스피 (226490) + KODEX 코스닥150 (229200), dynamically weighted by the eligible research universe's KOSPI/KOSDAQ market-cap split and rebalanced every 42 trading days.**

This two-ETF proxy is the **only pre-registered ETF candidate that passed every performance-fidelity gate**, and it also passed the whole-share cash-feasibility gates at KRW 10m, KRW 30m, and KRW 100m.

Therefore the earlier stock-only result — KRW 100m + Top 50 cap-weighted stocks — remains a valid **stock-basket baseline candidate**, but it is superseded as the preferred personal-quant baseline by the two-ETF proxy because the ETF implementation is executable at all tested capital tiers with dramatically lower order complexity.

No tested active factor strategy is promoted. The ETF result is a **benchmark translation**, not a new alpha strategy.

## Authoritative sources

ETF full run:

- GitHub Actions run: `32444932528`
- artifact: `kr-personal-quant-etf-proxy`
- artifact ID: `9433892498`
- artifact digest: `sha256:d8fc35d73cba12788e7ae41e91d2ceffeaf092d4d10ae3ca12639b60268a74f2`

Independent ETF price-source snapshot:

- GitHub Actions run: `32445510664`
- artifact ID: `9433914479`
- digest: `sha256:809d40774214565fd19cf8786330cacf519f00e59046e745df629895165bc204`

The lightweight artifact replay and the full panel rebuild agreed on CAGR, Sharpe, MDD, and tracking error to floating-point tolerance (maximum observed difference below `1e-16`).

Machine-readable results:

- `results/2026-08-21-etf-proxy-performance.csv`
- `results/2026-08-21-etf-proxy-capital.csv`
- prior stock-only result: `results/2026-08-21-personal-quant-baseline.csv`

## Pre-registration

ETF candidates and gates were frozen in PR #1 comment `5364956891` before ETF comparative performance was inspected.

Candidates:

1. `kodex_kospi` — 100% KODEX 코스피 (226490)
2. `kodex_200` — 100% KODEX 200 (069500)
3. `kodex_kospi_kq150_split` — KODEX 코스피 + KODEX 코스닥150 (229200), dynamic KOSPI/KOSDAQ eligible-universe market-cap split
4. `kodex_200_kq150_split` — KODEX 200 + KODEX 코스닥150, same dynamic split

Common rules:

- evaluation: 2018-01-01 through 2026-03-20
- FinanceDataReader `0.9.201`, `NAVER:` daily-price path
- no ETF cash-distribution reinvestment, matching the stock research benchmark's dividend-excluded price-return convention
- same 42-trading-day signal schedule
- T+1 execution
- same modeled costs as the stock research benchmark: buy 0.35%, sell 0.55%
- whole-share feasibility tested separately at KRW 10m / 30m / 100m

Performance fidelity gates:

- annualized tracking error <= 5.0%
- absolute CAGR gap <= 1.5 percentage points
- absolute Sharpe gap <= 0.10
- absolute MDD gap <= 5 percentage points
- ETF data coverage >= 99%

Whole-share gates:

- average residual cash <= 5%
- maximum residual cash <= 15%

Selection rule:

- every performance and lot gate must pass;
- among multiple passers, prefer fewer instruments, then lower tracking error;
- do not select a candidate because it had the highest historical return;
- do not weaken gates after observing results.

## Data audit

All three ETF price series passed the pre-registered integrity test.

| ETF | Rows (2017-12-01~2026-03-20) | Max abs 1-day move | >30% rows | Bad closes | Zero-volume rows |
|---|---:|---:|---:|---:|---:|
| KODEX 200 | 2,034 | 12.46% | 0 | 0 | 0 |
| KODEX 코스피 | 2,034 | 12.40% | 0 | 0 | 0 |
| KODEX 코스닥150 | 2,034 | 14.74% | 0 | 0 | 0 |

Within the actual 2018-01-02~2026-03-20 evaluation dates, each candidate leg had 100% coverage against the authoritative reference equity calendar.

## Authoritative reference reproduction

The ETF full runner rebuilt the common eligible universe and reproduced the existing fractional full-cap benchmark exactly at the guarded metrics:

- CAGR: **10.695381%**
- Sharpe: **0.599321**
- MDD: **-40.968565%**

Validation differences were `0.0` for CAGR, Sharpe, and MDD.

## ETF performance-fidelity result

| Candidate | CAGR | Sharpe | MDD | Tracking error | CAGR gap | Sharpe gap | Result |
|---|---:|---:|---:|---:|---:|---:|---|
| KODEX 코스피 | 12.92% | 0.717 | -41.27% | 4.10% | +2.23pp | +0.117 | **FAIL** |
| KODEX 200 | 14.70% | 0.761 | -38.09% | 4.28% | +4.00pp | +0.161 | **FAIL** |
| **KODEX 코스피 + 코스닥150 split** | **12.09%** | **0.671** | **-43.24%** | **3.66%** | **+1.40pp** | **+0.072** | **PASS** |
| KODEX 200 + 코스닥150 split | 13.75% | 0.718 | -40.48% | 3.48% | +3.05pp | +0.118 | **FAIL** |

The single-ETF and KODEX-200 variants are rejected **despite higher historical returns** because they drift too far from the benchmark under the pre-registered CAGR/Sharpe fidelity gates.

The selected two-ETF proxy is not the highest-return candidate. It is the candidate that actually satisfies the translation objective.

## Subperiod stability of the selected proxy

| Period | Full-cap Sharpe | Selected ETF proxy Sharpe |
|---|---:|---:|
| 2018–2021 | 0.386 | 0.403 |
| 2022–2024 | -0.398 | -0.233 |
| 2025–2026-03 | 2.636 | 2.695 |

Selected-proxy returns by subperiod:

- 2018–2021: +25.78%
- 2022–2024: -15.71%
- 2025–2026-03: +139.95%

The proxy preserves the same broad regime behavior as the full-cap benchmark rather than passing only because of one isolated subperiod.

## Whole-share feasibility by capital

For the selected KODEX 코스피 + KODEX 코스닥150 proxy:

| Capital | Avg residual cash | Max residual cash | Instruments achieved | Missing/untradable | Result |
|---:|---:|---:|---:|---:|---|
| KRW 10m | **0.191%** | **0.391%** | 2 / 2 at every snapshot | 0 | **PASS** |
| KRW 30m | **0.061%** | **0.161%** | 2 / 2 at every snapshot | 0 | **PASS** |
| KRW 100m | **0.0167%** | **0.0444%** | 2 / 2 at every snapshot | 0 | **PASS** |

This resolves the main weakness of the direct-stock translation. The stock basket required about KRW 100m before a Top-50 implementation passed the registered lot constraints; the ETF proxy passes from KRW 10m in the tested grid.

## Dynamic allocation rule

The selected baseline is **not a fixed 90/10 portfolio**.

At each 42-trading-day signal date:

1. rebuild the same eligible stock universe used by the benchmark;
2. sum eligible market capitalization separately for KOSPI and KOSDAQ;
3. set KODEX 코스피 weight = KOSPI eligible market cap / total eligible market cap;
4. set KODEX 코스닥150 weight = KOSDAQ eligible market cap / total eligible market cap;
5. execute the rebalance on T+1.

Across the 48 historical signal dates:

- average KOSPI weight: **89.90%**
- average KOSDAQ weight: **10.10%**
- KOSPI weight range: **86.02% to 93.63%**

The last backtest signal on 2026-01-19 was approximately:

- KODEX 코스피: **93.63%**
- KODEX 코스닥150: **6.37%**

That is a historical example only, not a current 2026-08 live allocation.

## Comparison with the stock-only candidate

Earlier direct-stock translation found:

- KRW 10m: no passing stock basket
- KRW 30m: no passing stock basket
- KRW 100m: Top 50 was the only passing stock-basket cell

The KRW 100m Top-50 stock candidate required roughly 311 transactions/year in the fractional tracking simulation and exhibited a maximum historical single-name target weight around 38.5%.

The selected ETF proxy requires only two instruments and passes the same practical cash gates at all tested capital tiers. For a personal quant whose objective is to establish a robust baseline before searching for alpha, the ETF proxy therefore has the better implementation profile.

## Current personal-quant hierarchy

1. **Preferred production baseline candidate:** KODEX 코스피 + KODEX 코스닥150, dynamic eligible-market-cap split
2. **Stock-only fallback / research comparator:** KRW 100m + Top-50 eligible stocks, cap-weighted
3. **Best tested active strategy:** Long-Reversal — retained for research, **not promoted**
4. KR-CORE / other tested active models — rejected under the existing tournament

## What is and is not proven

Proven under this retrospective/pseudo-OOS research framework:

- the two-ETF proxy tracks the winning full-cap research benchmark within every pre-registered performance gate;
- whole-share implementation is feasible at KRW 10m, KRW 30m, and KRW 100m;
- the result independently reproduces through both a full common-panel rebuild and an artifact-based replay.

Not proven:

- genuine untouched forward OOS alpha;
- that the ETF proxy is globally optimal;
- that live slippage/taxes will exactly match the conservative stock-cost assumptions;
- that the historical last allocation should be used today without rebuilding current data.

## Next production phase

The benchmark-selection phase is now complete enough to stop searching for another baseline on the same history.

The next useful work is **productionization**, not further historical tuning:

1. build a current eligible-universe market-cap split calculator;
2. produce exact two-ETF whole-share target orders from account equity and T+1/current executable prices;
3. add drift / rebalance threshold reporting without changing the registered 42-day research rule until separately tested;
4. paper-run the ETF baseline forward;
5. only then compare genuinely new active challengers against this investable ETF baseline.

Do not retune the ETF blend, Top-N, KR-CORE, or Long-Reversal on the same 2018–2026 history merely to improve the historical score.
