# Forward ETF Shadow Runbook

Research ID: `RL-2026-08-22-ETF-FORWARD-001`

Preregistration: PR #1 comment `5380855734`  
Implementation freeze: PR #1 comment `5380875031`  
Durable signal ledger: issue #18

This runbook is operational only. It does not add a strategy, change a gate, or permit historical reconstruction.

## 1. Non-negotiable rules

1. The confirmatory sample does not begin until the first 84-actual-KRX-session control signal strictly after 2026-08-22.
2. The original historical cadence anchor remains `2018-01-02`.
3. The immutable accepted robustness artifact proves 24 historical 84d signals ending at `2025-11-17`; `data/accepted_84d_control_schedule.json` freezes those dates and source hashes.
4. Runtime cadence continues from that already-verified `2025-11-17` signal by 84 **actual** KRX trading sessions. This is the same sequence as rebuilding from 2018, without requiring the forward feature DB to retain all 2018-present prices.
5. Current calendar expectation for the first forward control signal is `2026-11-27`; actual KRX trading-session count overrides this expected date.
6. T+1 execution convention is unchanged.
7. A missing signal is never recreated from a later raw-data snapshot. Record it as missing instead.
8. Signal/state JSON and its hash must be persisted to issue #18 before the next session close.
9. No performance gate is evaluated before 504 completed forward sessions. The 126/252-session checkpoints are diagnostics only.

## 2. Frozen strategy primitives

### Control

- KODEX KOSPI `226490`
- KODEX KOSDAQ150 `229200`
- eligible-universe KOSPI/KOSDAQ market-cap split
- accepted PIT universe methodology uses frozen AlphaKRX method SHA `e773d4243b7a644dd0c525daccebdf062bc389a1`
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

## 3. Snapshot provenance and data gates

Methodology and raw data are intentionally versioned separately.

Record all of the following for every event:

- forward implementation commit SHA;
- frozen AlphaKRX methodology SHA;
- AlphaKRX raw-financial snapshot SHA used that day;
- FinanceData/marcap snapshot SHA used that day;
- KRX calendar file SHA256/version;
- accepted 84d schedule-proof source/digest;
- forward DB SHA256;
- DB market max date;
- latest financial `available_date`;
- FinanceDataReader version;
- normalized source CSV SHA256 for both ETFs.

The DB builder hard-fails when:

- market max date is earlier than the requested signal date;
- market max date is later than the requested signal date (later replay/backfill);
- any financial `available_date` is later than the requested signal date;
- the frozen methodology SHA changes.

The authoritative entrypoint `scripts/run_forward_etf_shadow.py` additionally hard-fails when the latest PIT financial `available_date` is more than **180 calendar days** behind the signal-day market snapshot. This reuses the already-established production freshness standard; it never changes the universe rule to rescue a stale feed.

## 4. Efficient DB build

The signal-day feature core does not need a new 2011-present tournament DB. For a signal in year `Y`, the frozen feature core needs approximately `Y-2..Y` prices, while cadence continuation needs the accepted `2025-11-17` control anchor.

Therefore:

- feature warm-up start = `Y-2`;
- cadence anchor retention start = `2025`;
- effective `PRICE_START_YEAR = min(Y-2, 2025)`.

For 2026 this means 2024 onward. For later years the DB keeps 2025 onward so the immutable continuation anchor remains present. PIT financial history stays available from 2015 onward.

The marcap cache is namespaced by exact `marcap_sha`; never reuse a yearly parquet across different source SHAs.

Pseudo-shell outline:

```bash
SIGNAL_DATE=YYYYMMDD
SIGNAL_YEAR=${SIGNAL_DATE:0:4}
FEATURE_START_YEAR=$((SIGNAL_YEAR-2))
if [ "$FEATURE_START_YEAR" -gt 2025 ]; then
  PRICE_START_YEAR=2025
else
  PRICE_START_YEAR=$FEATURE_START_YEAR
fi

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

python scripts/run_forward_etf_shadow.py \
  --method-alphakrx-root vendor/alphakrx-method \
  --db work/forward_${SIGNAL_DATE}.db \
  --signal-date "$SIGNAL_DATE" \
  --snapshot-manifest outputs/forward_${SIGNAL_DATE}/snapshot_manifest.json \
  --calendar data/krx_market_calendar_2025_2029.json \
  --implementation-sha "$IMPLEMENTATION_SHA" \
  --output outputs/forward_${SIGNAL_DATE}
```

`run_forward_etf_shadow.py` validates the immutable accepted schedule proof and 180-day PIT freshness, then delegates unchanged strategy calculations to `generate_forward_etf_shadow_signal.py` while sourcing runtime trading dates from the verified `2025-11-17` continuation anchor.

## 5. Event handling

### Before first forward control

Monthly 10M observations are warm-up only. Do not post them as confirmatory events.

### First forward control

Freeze:

- 84d base weights;
- most recent **completed** month-end 10M state;
- all provenance hashes.

Under the current calendar, if the first control is `2026-11-27`, November is not complete; the trend initializer must therefore come from the latest completed month, currently expected October 2026.

### Later calendar month-end

Freeze the new 10M state and T+1 expected execution date. Base weights remain the last frozen 84d control weights unless the same date is also an 84d control event.

### Later 84d control

Freeze the new market-split weights and the latest completed 10M state for deterministic state continuity.

## 6. Failure semantics

- `NO_EVENT`: valid same-day snapshot but neither a forward 84d control nor a post-start completed month-end.
- `DATA_NOT_READY`: market/financial/ETF source is stale or incomplete on the required day. No signal is manufactured.
- `REPLAY_BLOCKED`: a later source snapshot contains dates unavailable on the requested historical signal date. No backfill.
- `FORWARD_EVENT_FROZEN`: event primitives and provenance were persisted before subsequent returns.

Do not convert `DATA_NOT_READY`, `REPLAY_BLOCKED`, or a missed run into a reconstructed signal after seeing later returns.

## 7. GitHub Actions automation

The production scheduler is `.github/workflows/forward-etf-shadow-scheduled.yml` and becomes active only after it exists on the repository default branch.

### Daily lightweight gate

On KRX weekdays it runs at **22:20 and 23:20 Asia/Seoul**. `scripts/check_forward_etf_shadow_due.py` uses only the frozen KRX calendar and accepted cadence proof to decide whether a heavy same-day freeze may be required.

- normal non-event days stop after the lightweight gate;
- event days build the PIT DB and invoke `run_forward_etf_shadow.py`;
- the second same-day run checks issue #18 and becomes a no-op if the first run already persisted `FORWARD_EVENT_FROZEN`;
- if the first attempt fails because data are not ready, a second **same-day** attempt is allowed before subsequent returns;
- a later-date replay remains forbidden and is rejected by the market-snapshot guard.

The calendar gate is not authoritative for the 84d cadence. The same-day DB's actual trading dates and the frozen runner are authoritative before a control event is accepted.

### Durable ledger

A successful event writes the signal Markdown, canonical signal JSON, preflight provenance, hashes, and GitHub run reference to issue #18. Artifacts are also retained for 90 days, but the issue ledger is the durable record.

A failed due-date run writes an explicit failure record to issue #18 so that a missing signal cannot later be silently reconstructed.

### Public-repository scheduler keepalive

GitHub may automatically disable scheduled workflows in a public repository after 60 days without repository activity. The scheduler therefore runs a **monthly 04:17 Asia/Seoul heartbeat** that updates `docs/research/forward-scheduler-heartbeat.txt` with a `[skip ci]` commit. This creates repository activity without changing research code or strategy state.

Official GitHub references:

- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows
- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

The heartbeat is operational infrastructure only. It is not a forward observation and does not alter the implementation rules, benchmark, challenger, or evaluation gates.
