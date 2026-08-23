# Forward ETF Shadow Runbook

Research ID: `RL-2026-08-22-ETF-FORWARD-001`

Preregistration: PR #1 comment `5380855734`  
Implementation freeze: PR #1 comment `5380875031`  
Durable signal ledger: issue #18

This runbook is operational only. It does not add a strategy, change a gate, or permit historical reconstruction.

## 1. Non-negotiable rules

1. The confirmatory sample does not begin until the first 84-actual-KRX-session control signal strictly after 2026-08-22.
2. The historical 84d anchor remains `2018-01-02`.
3. A fresh trading-date list must reproduce the already-audited historical last signal `2025-11-17` before any forward control signal is accepted.
4. Current calendar expectation for the first forward control signal is `2026-11-27`; actual KRX trading-session count overrides this expected date.
5. T+1 execution convention is unchanged.
6. A missing signal is never recreated from a later raw-data snapshot. Record it as missing instead.
7. Signal/state JSON and its hash must be persisted to issue #18 before the next session close.
8. No performance gate is evaluated before 504 completed forward sessions. The 126/252-session checkpoints are diagnostics only.

## 2. Frozen strategy primitives

### Control

- KODEX KOSPI `226490`
- KODEX KOSDAQ150 `229200`
- eligible-universe KOSPI/KOSDAQ market-cap split
- accepted PIT universe methodology uses the frozen AlphaKRX method SHA `e773d4243b7a644dd0c525daccebdf062bc389a1`
- research feature/universe horizon remains 42 sessions; only ETF target-weight refresh cadence is 84 sessions

### 10M trend overlay

For each ETF independently:

- use the last common ETF close of a **completed calendar month**;
- SMA10 = arithmetic mean of the latest 10 completed month-end closes, including the current completed month;
- ON iff month-end close > SMA10;
- OFF sleeve goes to cash;
- remaining ON sleeve is **not** renormalized;
- cash return assumption remains 0;
- month-end state changes execute T+1.

A partial current month must never be treated as a completed month. In particular, under the current calendar `2026-11-27` is not November month-end because `2026-11-30` is still a scheduled KRX session.

## 3. Snapshot provenance

Methodology and raw data are intentionally versioned separately.

Record all of the following for every event:

- forward implementation commit SHA;
- frozen AlphaKRX methodology SHA;
- AlphaKRX raw-financial snapshot SHA used that day;
- FinanceData/marcap snapshot SHA used that day;
- KRX calendar file SHA256/version;
- forward DB SHA256;
- DB market max date;
- latest financial `available_date`;
- FinanceDataReader version;
- normalized source CSV SHA256 for both ETFs.

The builder hard-fails when:

- market max date is earlier than the requested signal date;
- market max date is later than the requested signal date (later replay/backfill);
- any financial `available_date` is later than the requested signal date;
- the frozen methodology SHA changes.

Operational freshness guard: the same pre-existing production standard remains applicable — if the latest financial `available_date` is more than 180 calendar days behind the market snapshot, do not freeze a live/forward control signal. Record a data-quality failure instead of changing the universe rule.

## 4. Efficient DB build

The signal-day feature core only needs the frozen year-chunk warm-up, not a new 2011-present historical tournament rebuild. For a signal in year `Y`, use market prices from `Y-2` through `Y` (the frozen core uses Jan 1 of `Y` minus 420 calendar days) while retaining PIT financial history from 2015 onward.

The marcap cache must be namespaced by exact `marcap_sha`. Never reuse `marcap-Y.parquet` across different source SHAs.

Pseudo-shell outline:

```bash
SIGNAL_DATE=YYYYMMDD
SIGNAL_YEAR=${SIGNAL_DATE:0:4}
PRICE_START_YEAR=$((SIGNAL_YEAR-2))

# Resolve these on the signal day and persist the SHAs before later returns.
METHOD_ALPHAKRX_SHA=e773d4243b7a644dd0c525daccebdf062bc389a1
DATA_ALPHAKRX_SHA=<current AlphaKRX raw-data snapshot SHA>
MARCAP_SHA=<current FinanceData/marcap snapshot SHA>
IMPLEMENTATION_SHA=<frozen forward implementation SHA>

python scripts/build_forward_research_db.py \
  --method-alphakrx-root vendor/alphakrx-method \
  --data-alphakrx-root vendor/alphakrx-data \
  --method-alphakrx-sha "$METHOD_ALPHAKRX_SHA" \
  --data-alphakrx-sha "$DATA_ALPHAKRX_SHA" \
  --marcap-sha "$MARCAP_SHA" \
  --signal-date "$SIGNAL_DATE" \
  --start-year "$PRICE_START_YEAR" \
  --financial-start-year 2015 \
  --db work/forward_${SIGNAL_DATE}.db \
  --manifest outputs/forward_${SIGNAL_DATE}/snapshot_manifest.json

python scripts/generate_forward_etf_shadow_signal.py \
  --method-alphakrx-root vendor/alphakrx-method \
  --db work/forward_${SIGNAL_DATE}.db \
  --signal-date "$SIGNAL_DATE" \
  --snapshot-manifest outputs/forward_${SIGNAL_DATE}/snapshot_manifest.json \
  --calendar data/krx_market_calendar_2025_2029.json \
  --implementation-sha "$IMPLEMENTATION_SHA" \
  --output outputs/forward_${SIGNAL_DATE}
```

## 5. Event handling

### Before first forward control

Monthly 10M observations are warm-up only. Do not post them as confirmatory events.

### First forward control

Freeze:

- 84d base weights;
- most recent **completed** month-end 10M state;
- all provenance hashes.

Under the current calendar, if the first control is `2026-11-27`, the current-month November state is not complete; the trend initializer must therefore come from the latest completed month (currently expected October 2026).

### Later calendar month-end

Freeze the new 10M state and T+1 expected execution date. The base weights remain the last frozen 84d control weights unless the same date is also an 84d control event.

### Later 84d control

Freeze the new market-split weights. Also record the latest completed 10M state for deterministic state continuity.

## 6. Failure semantics

- `NO_EVENT`: valid same-day snapshot but neither a forward 84d control nor a post-start completed month-end.
- `DATA_NOT_READY`: market/financial/ETF source is stale or incomplete on the required day. No signal is manufactured.
- `REPLAY_BLOCKED`: a later source snapshot contains dates unavailable on the requested historical signal date. No backfill.
- `FORWARD_EVENT_FROZEN`: event primitives and provenance were persisted before subsequent returns.

Do not convert `DATA_NOT_READY`, `REPLAY_BLOCKED`, or a missed run into a reconstructed signal after seeing later returns.
