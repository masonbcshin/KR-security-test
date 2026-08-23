# ETF Safe-Sleeve Implementation Verdict — PENDING_EXECUTION_INFRA

## Current status

The personal-quant Core remains:

> **60% equity / 40% defensive risk budget, with the equity sleeve implemented by the accepted KODEX KOSPI (226490) + KODEX KOSDAQ150 (229200) dynamic eligible-market-cap split and refreshed every 84 trading days, T+1.**

The 60/40 risk-budget selection is already accepted. This document concerns only the implementation of the 40% defensive sleeve.

**No defensive-ETF candidate has been promoted yet.** Until the frozen implementation study executes successfully, the authoritative historical baseline remains **40% zero-yield cash**.

Status code: `PENDING_EXECUTION_INFRA`.

## Frozen full-history candidates

Pre-registration: PR #1 comment `5383435992`.

1. `cash_zero` — 40% strategic cash, 0% return
2. `214980` — KODEX 단기채권PLUS
3. `273140` — KODEX 단기변동금리부채권액티브

Current KOFR/CD ETFs are not eligible to win the 2018-2026 historical selection because they were listed after the test began:

- `423160` KODEX KOFR금리액티브 — post-inception operational diagnostic only
- `459580` KODEX CD금리액티브 — post-inception operational diagnostic only

No synthetic pre-inception backfill is permitted.

## Frozen equity/risk-budget mechanics

- equity exposure: 60%
- defensive exposure: 40%
- exact accepted 226490/229200 relative weights
- 84-trading-day refresh
- T+1 target changes
- no daily rebalancing
- no leverage, trend timing, vol targeting, stop loss, or exposure retuning
- conservative modeled transaction cost: buy 0.35%, sell 0.55%
- defensive ETF: actual third instrument, whole shares; residual cash remains cash

The runner must first reproduce the accepted 60/40 zero-yield baseline within `1e-10` for CAGR, Sharpe, MDD and Calmar. If this guard fails, the implementation study is invalid.

## Distribution-accounting corrections locked before results

The original price-only plan was superseded before any candidate result was observed because market close returns exclude ETF distributions.

PR #1 methodology amendments:

- `5383468340` — add disclosed distributions to the defensive-sleeve cash flows
- `5383469585` — selection uses the conservative after-tax reconstruction
- `5383492708` — add the historical 2018 year-end distributions discovered during source audit

Frozen disclosed distributions inside the test window:

### 214980

- 2018-12-27: KRW 1,785/share
- 2025-08-13: 244
- 2025-09-12: 236
- 2025-10-14: 232
- 2025-11-13: 238
- 2025-12-12: 236
- 2026-01-14: 251
- 2026-02-12: 258
- 2026-03-12: 239

### 273140

- 2018-12-27: KRW 1,640/share
- 2025-08-13: 238
- 2025-09-12: 227
- 2025-10-14: 228
- 2025-11-13: 233
- 2025-12-12: 232
- 2026-01-14: 246
- 2026-02-12: 238
- 2026-03-12: 228

Official later histories indicate no distribution events in 2019-2024. Distribution cash is retained until the next scheduled 84-day refresh rather than immediately reinvested.

## Conservative taxable selection

The promotion gates are applied to the `conservative_after_tax` result, not the gross result.

Modeled tax:

- 15.4% on disclosed distributions
- 15.4% on every positive realized defensive-ETF market-price gain

The second rule is intentionally adverse. Actual Korean ETF sale taxation uses the lesser of market gain and the standard-tax-base increase, so the frozen model can overstate tax. A defensive ETF must still pass under this conservative approximation to be promoted.

## Frozen promotion gates vs zero-yield 60/40 baseline

A full-history defensive ETF can advance only if all hold:

1. MDD no worse by more than 1.0 percentage point
2. Sharpe no worse by more than 0.03
3. Calmar no worse by more than 10%
4. CAGR no worse by more than 0.50 percentage point
5. worst five-year total return no worse by more than 2 percentage points
6. no data-integrity or execution-feasibility failure

Among passers, choose by:

1. lower MDD
2. higher Sharpe
3. higher Calmar
4. lower operational complexity / modeled cost

CAGR alone cannot select the winner.

## Execution blocker

The current GitHub Actions safe-sleeve runs fail before any runner step is created (`steps=null`, no job logs). Unrelated workflows on the same PR fail in the same pre-step state. Therefore these failures are classified as execution-infrastructure failures, not strategy results.

The code and workflow are prepared:

- `scripts/run_etf_safe_sleeve_study.py`
- `.github/workflows/etf-safe-sleeve-study.yml`

The workflow guard now requires the frozen 2018 distributions, 2025-2026 monthly distributions, 15.4% tax rate and conservative-after-tax selection mode to be present before execution.

## Decision while blocked

- **Historical canonical defensive sleeve:** `cash_zero` (temporary baseline, not claimed optimum)
- **214980 / 273140:** pending frozen execution; neither is promoted or rejected
- **423160 / 459580:** operational diagnostics only; cannot retroactively win the full-history study
- **Do not add/tune candidates, exposure levels, duration buckets or rebalance intervals while blocked.**

Once execution infrastructure is available, run the frozen study exactly once under the above rules, persist `comparison.csv`/`result.json`, and replace this pending status with the observed verdict. No rescue tuning is allowed.
