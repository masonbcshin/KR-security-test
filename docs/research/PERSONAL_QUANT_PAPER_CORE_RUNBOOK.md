# Personal-Quant PAPER Core Runbook

Status: implementation freeze

This runbook translates the accepted investable Core into a forward-only PAPER execution layer. It does **not** change the strategy, backtest, risk budget, cadence, universe, or promotion gates.

## Frozen strategy

- Equity sleeve: 60%
  - KODEX KOSPI `226490`
  - KODEX KOSDAQ150 `229200`
  - relative weights = eligible-universe KOSPI/KOSDAQ market-cap split
- Defensive sleeve: 40%
  - KODEX 단기채권PLUS `214980`
- Refresh cadence: every 84 actual KRX trading sessions
- Original cadence anchor: `2018-01-02`
- Accepted historical continuation anchor: `2025-11-17`
- Execution convention: T+1
- Research universe/feature horizon remains 42 sessions
- No leverage, stop, trend overlay, vol targeting, tactical cash, or exposure retuning

## PAPER-only safety rules

1. No brokerage API import or order submission code is permitted in this phase.
2. A synthetic KRW 100,000,000 paper account is used for execution-path validation.
3. The first eligible paper control is the first 84-session signal strictly after this implementation freeze. Current calendar expectation is `2026-11-27`; actual KRX session count wins.
4. Signals are never reconstructed from a later snapshot after returns are known.
5. Market data must be same-day and PIT financial availability must be <=180 calendar days stale versus the signal date.
6. If data gates fail, status is `DATA_NOT_READY` and no paper order is created.
7. A canonical `signal_id` is hashed from strategy ID, signal date, execution date and target weights. The same signal ID can be processed only once.
8. Before T+1, status is `WAITING_T1`; no fill is recorded.
9. On T+1 after a valid price snapshot, sell deltas are processed before buy deltas. Whole shares are used for all three ETFs in the paper execution layer.
10. Cash may not go negative. Residual cash remains cash.
11. PAPER results do not change the frozen strategy. They validate data/execution fidelity only.

## Data-source rule

The current AlphaKRX raw financial tree is not considered a sufficient live source by itself because it is not guaranteed to be refreshed before every paper signal. The runner must report the actual maximum PIT `available_date` used. If it is >180 days stale, the signal is blocked rather than changing the universe.

OpenDART's official financial-information bulk download is the intended upstream source for refreshing the raw financial ZIP snapshot. A future automated downloader may replace the stale snapshot only if it preserves the filing/availability date semantics used by the frozen ETL.

## Acceptance tests

The implementation is acceptable only when all pure self-tests pass:

- final weights sum to 1.0 and defensive weight is exactly 0.40;
- equity child weights sum to exactly 0.60;
- duplicate signal IDs are idempotent (`NOOP_DUPLICATE`);
- pre-T+1 execution is blocked (`WAITING_T1`);
- stale data produces no orders (`DATA_NOT_READY`);
- whole-share fills never create negative cash;
- re-running an already filled signal does not change holdings/cash;
- no module contains brokerage submission logic.

The forward PAPER ledger begins only with a genuinely future signal observed after this freeze. Historical backfill is forbidden.
