# ETF Safe-Sleeve Implementation Verdict — FINAL

## Decision

The accepted personal-quant Core is now:

> **60% equity / 40% defensive sleeve**
>
> Equity sleeve: KODEX KOSPI (226490) + KODEX KOSDAQ150 (229200), dynamic eligible-market-cap split, refreshed every 84 trading days, T+1.
>
> Defensive sleeve: **KODEX 단기채권PLUS (214980)**, reset to 40% only on the same 84-trading-day refreshes.

Status code: `FINAL_SELECTED_214980`.

## Authoritative execution

The previously blocked frozen study was rerun after the repository was made public, which restored GitHub-hosted runner allocation.

- workflow run: `32632491941`
- job: `97335047443`
- conclusion: `success`
- artifact: `kr-etf-safe-sleeve-study`
- artifact id: `9508488280`
- artifact digest: `sha256:a7cb99a0abedb0186aea12438acf20dd56c988d13d54baa27d2d2ad08aa679cf`
- run head: `accdca6a703c3dfddeb084ce2466816e8656901d`

The baseline-reproduction guard, preregistration guard, immutable-artifact download, frozen study, and artifact upload all passed.

## Frozen full-history candidates

Pre-registration: PR #1 comment `5383435992`.

1. `cash_zero` — 40% strategic cash, 0% return
2. `214980` — KODEX 단기채권PLUS
3. `273140` — KODEX 단기변동금리부채권액티브

KOFR/CD ETFs remained post-inception diagnostics only and were not eligible to win the 2018-2026 selection.

## Conservative after-tax authoritative results

| Candidate | CAGR | Sharpe | MDD | Calmar | Worst 5y total return | End equity | Frozen gates |
|---|---:|---:|---:|---:|---:|---:|---|
| cash_zero | 7.7500% | 0.672565 | -27.2211% | 0.284706 | -0.1808% | KRW 184.575m | baseline |
| **214980** | **8.6221%** | **0.738776** | **-25.6397%** | **0.336279** | **+3.2116%** | **KRW 197.205m** | **PASS all / SELECTED** |
| 273140 | 8.6101% | 0.738112 | -25.8092% | 0.333607 | +3.2039% | KRW 197.027m | PASS all |

Both defensive ETFs passed every frozen promotion gate. The pre-registered tie-break then selected `214980` because it had the lower MDD, with slightly higher Sharpe and Calmar as well.

## Improvement vs zero-yield 60/40 baseline

Using the deliberately conservative taxable model:

- CAGR: 7.75% -> **8.62%**
- Sharpe: 0.673 -> **0.739**
- MDD: -27.22% -> **-25.64%**
- Calmar: 0.285 -> **0.336**
- worst five-year total return: -0.18% -> **+3.21%**
- end equity on KRW 100m: 184.575m -> **197.205m**

The model charged 15.4% on disclosed distributions and also 15.4% on every positive realized defensive-sleeve market-price gain. This can overstate actual Korean ETF holding-period tax, so the selected result is intentionally conservative.

For 214980 the modeled tax was:

- distribution gross: KRW 1,708,158
- distribution tax: KRW 263,056
- modeled realized-gain tax: KRW 1,175,693
- total modeled tax: KRW 1,438,749

## Distribution accounting

Methodology corrections were locked before any candidate result was observed:

- `5383468340` — disclosed distributions added to cash flow
- `5383469585` — conservative after-tax row used for selection
- `5383492708` — historical 2018 year-end distributions added

Distribution cash is held until the next scheduled 84-day refresh rather than immediately reinvested.

## Final personal-quant baseline

The current tested implementation baseline is therefore:

> **60% equity / 40% KODEX 단기채권PLUS (214980)**
>
> Equity 60% = 226490 + 229200 in the accepted dynamic eligible-market-cap split.
>
> Rebalance every 84 trading days, target changes T+1.

This is a low-frequency systematic asset-allocation baseline, not a proven alpha strategy. The historical test still covers the same 2018-01-01 through 2026-03-20 window and should not be interpreted as an independent future OOS guarantee.

No additional safe-sleeve ETF, exposure ratio, duration bucket, or cadence should be tuned on this same history to rescue or improve the result.