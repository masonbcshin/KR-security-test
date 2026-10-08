# Data-source amendment — 2026-09-02

This amendment was made after the first unified run failed **before any strategy performance result was observed**.

## Failure observed
The original unified harness attempted to recompute historical KOSPI/KOSDAQ150 market-cap splits through `pykrx`. On 2026-09-02 the current KRX-backed interface required `KRX_ID` / `KRX_PW`, so the public GitHub runner could not retrieve the historical market-cap panel.

## Authoritative recovery
Instead of approximating the split, the exact previously validated 84-trading-day signal file was recovered from the successful public GitHub Actions run:

- repository: `masonbcshin/KR-security-test`
- workflow: `ETF rebalance cadence robustness`
- run: `32492902475`
- artifact: `9450776179` (`kr-etf-rebalance-robustness`)
- source file: `etf_rebalance_robustness/cadence_84d/signals.csv`
- source methodology label: pre-registered ETF rebalance-cadence robustness test

The recovered signal weights are committed as `pq_84d_authoritative_signals.csv` and are used without alteration inside the 60% equity sleeve. The remaining 40% is `214980`.

## Common end-date amendment
The authoritative PQ source run was frozen with `end=20260320`. To avoid inventing post-source PQ market-cap weights, the final apples-to-apples historical tournament is therefore capped at **2026-03-20** for all four strategies.

This is a data-availability amendment, not a performance-driven parameter change. The original no-retuning and v2 promotion rules remain unchanged.
