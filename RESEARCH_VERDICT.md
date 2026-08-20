# Korean Stock Strategy Research Verdict — 2026-08-20

## Decision

**No tested active strategy is promoted to production.**

Under the common 2018-01-01 through 2026-03-20 retrospective/pseudo-OOS tournament, the cost-matched `universe_cap` research benchmark remains the risk-adjusted winner.

This does **not** prove that cap weighting is globally optimal. It means that, among the strategies actually tested under the current common rules, no active candidate demonstrated enough after-cost evidence to displace the benchmark.

## Authoritative full-period comparison

| Rank | Strategy | Status | Total return | CAGR | Sharpe | MDD | Calmar | Transaction cost |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | `universe_cap` | research winner | +130.32% | 10.70% | **0.599** | -40.97% | **0.261** | ₩2.59m |
| 2 | `lowvol_trend_long_reversal` | best active, rejected | +83.94% | 7.71% | 0.471 | -51.59% | 0.149 | ₩28.62m |
| 3 | corrected `lowvol_trend` | rejected | +78.48% | 7.31% | 0.449 | -52.53% | 0.139 | ₩25.70m |
| 4 | `q5_proxy` | rejected | +54.48% | 5.44% | 0.354 | -46.53% | 0.117 | ₩13.49m |
| 5 | corrected `kr_core_portable` | rejected | +27.37% | 2.99% | 0.249 | -47.88% | 0.062 | ₩26.53m |
| 6 | `portable_full_ml` | rejected | +1.95% | 0.24% | 0.127 | -58.89% | 0.004 | ₩21.34m |

The machine-readable source of this table is `results/2026-08-20-authoritative-comparison.csv`.

## Long-reversal challenger

The next challenger was registered in PR #1 **before its result was observed**. It preserved every corrected LowVol+Trend rule and changed exactly one sign:

- `mom_36m`: `+1` momentum -> `-1` long-horizon reversal

The corrected `mom_36m` characteristic is the cumulative monthly return from `t-36` through `t-13`, not the most recent 756-trading-day return.

Result:

- corrected LowVol+Trend Sharpe: `0.449`
- preregistered Long-Reversal Sharpe: `0.471`
- fractional cap benchmark Sharpe: `0.599`

So the reversal hypothesis improved the active strategy but still failed the promotion gate.

### Subperiod check

| Period | Cap benchmark | Long reversal | Interpretation |
|---|---:|---:|---|
| 2018–2021 Sharpe | 0.386 | 0.331 | benchmark ahead |
| 2022–2024 Sharpe | -0.398 | 0.195 | reversal materially ahead |
| 2025–2026-03 Sharpe | 2.636 | 1.361 | benchmark dominates concentrated large-cap rally |
| 2022–2026 Sharpe | 0.777 | 0.615 | benchmark ahead over the full later regime |

The active result is therefore regime-sensitive. It provided useful protection/selection in 2022–2024, but that was not enough to offset its weaker exposure to the 2025–2026 concentration regime.

## Corrections made during the audit

### 1. Samsung Electronics market-cap anomaly suspicion — rejected

A full-DB maximum market cap near ₩2,119tn initially looked suspicious. Focused audit showed it occurred on 2026-06-18 at a ₩362,500 close with an implied common-share count around 5.85bn. The market-cap scale was consistent with the source data and external market context. It was not a 2011–2017 marcap unit error.

### 2. `mom36m` implementation — corrected

The first implementation incorrectly used the most recent 756-trading-day return. The corrected portable implementation uses monthly prices and computes the cumulative return from months `t-36` through `t-13`.

The original full-run KR-CORE result produced with the 756-day implementation is invalid as a KR-CORE result and must not be used for model selection.

### 3. Missing `conditional_momentum` — corrected

The intended KR-CORE feature list contains 11 features. The initial portable implementation had only 10 and omitted `conditional_momentum`.

The corrected run restored all 11 features. Two independent GitHub Actions runs produced byte-identical `comparison.csv` and KR-CORE `summary.json`, confirming deterministic reproduction under the fixed seed and common data.

### 4. VKOSPI limitation — still open

The exact frozen KR-CORE definition uses:

`conditional_momentum = mom_21d * (1 - vkospi_level_pct)`

The public portable research DB does not contain historical `deriv_index_daily` / VKOSPI. The pinned AlphaKRX feature layer therefore applies its neutral fallback `vkospi_level_pct = 0.5`.

Consequently the corrected result is accurately labeled **`kr_core_portable`**, not an exact reproduction of the frozen VKOSPI-conditioned KR-CORE v1.

This limitation does not make the corrected portable result disappear; it means the exact frozen-v1 hypothesis remains technically untested until a point-in-time historical VKOSPI series is supplied.

### 5. Corrected-run benchmark wrapper — identified and isolated

The first corrected workflow invoked the base tournament directly and therefore reverted the cap benchmark to integer shares. The original full CI path and the long-reversal challenger use the intended fractional-share cap benchmark.

The benchmark **signals were byte-identical** between the original full run and the challenger. Therefore the authoritative comparison combines:

- corrected strategy results from the deterministic corrected runs; and
- the unchanged fractional benchmark from the original full/challenger runs.

The integer-share benchmark row emitted by the first corrected artifact is not authoritative.

## What the result means

1. **KR-CORE is no longer the selected Korean strategy.** The corrected portable version improved materially versus the broken implementation, but still fell well short of the benchmark after costs.
2. **Long-horizon reversal is useful, but insufficient alone.** Flipping `mom36m` improved the strongest static active candidate without tuning other parameters, which is evidence worth retaining.
3. **Turnover is a major burden.** Long reversal incurred about ₩28.6m of cumulative modeled transaction costs on a ₩100m starting portfolio, versus about ₩2.6m for the cap benchmark.
4. **The 2025–2026 concentration regime matters.** The cap benchmark's strongest advantage appears in the recent large-cap-dominated regime, but the benchmark also beat reversal in 2018–2021, so the conclusion cannot be dismissed as a single recent episode.
5. **Historical active edge is not robust enough for promotion.** The best active candidate did beat the benchmark in 2022–2024, but not across the complete test or the predefined broader subperiods.

## Research status

- `K-QGIT v0`: rejected before implementation tournament.
- original `KR-RANK v1`: superseded / unproven.
- broken initial `kr_core_portable`: invalid for selection because of implementation mismatch.
- corrected `kr_core_portable`: **rejected as production candidate** under the portable test.
- corrected `lowvol_trend`: rejected.
- preregistered `lowvol_trend_long_reversal`: **best active candidate, but rejected for production promotion**.
- `universe_cap`: **current research winner / benchmark**, not yet a directly deployable Korean-stock portfolio because the research implementation uses fractional shares across the whole eligible universe.

## Next phase

Do **not** tune KR-CORE or Long-Reversal on the same 2018–2026 history to make them beat the benchmark.

The next useful phase is translation of the winning research baseline into an actually investable production baseline (for example a separately pre-registered integer-share / index-proxy implementation) and then comparison of any genuinely new active challenger against that baseline. Any new target, feature set, concentration rule, or market-regime rule must be registered as a separate challenger before its historical result is inspected.
