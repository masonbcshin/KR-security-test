#!/usr/bin/env python3
"""Generate forward-only ETF shadow signal primitives.

RL-2026-08-22-ETF-FORWARD-001

This script does not backtest, calculate performance, or choose among strategies.
It only freezes the information that the two preregistered strategies would have
known on an eligible forward signal date:

1. 84-trading-session control base weights (KODEX KOSPI / KOSDAQ150), and
2. the frozen 10-month calendar-month-end trend state.

The first forward sample starts at the first 84d control signal strictly after
2026-08-22.  Before that control event, monthly trend observations are only
indicator warm-up and are not forward sample events.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import FinanceDataReader as fdr
import numpy as np
import pandas as pd

import run_etf_proxy_baseline as ep
import run_portable_tournament as rpt
from run_long_reversal_challenger import _register_corrected_mom36

RESEARCH_ID = "RL-2026-08-22-ETF-FORWARD-001"
PREREG_COMMENT_ID = 5380855734
IMPLEMENTATION_FREEZE_COMMENT_ID = 5380875031
FREEZE_DATE = "20260822"
ANCHOR_DATE = "20180102"
EXPECTED_FIRST_FORWARD_CONTROL = "20261127"  # calendar expectation, not a manual anchor
CADENCE = 84
TARGET_HORIZON = 42
CODES = ["226490", "229200"]
CODE_LABELS = {"226490": "KODEX KOSPI", "229200": "KODEX KOSDAQ150"}
SMA_MONTHS = 10
FDR_VERSION = "0.9.201"
METHOD_ALPHAKRX_SHA = "e773d4243b7a644dd0c525daccebdf062bc389a1"
MAX_ABS_ETF_MOVE = 0.30
BUY_COST = 0.0035
SELL_COST = 0.0055


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--method-alphakrx-root", required=False)
    p.add_argument("--db", required=False)
    p.add_argument("--signal-date", required=False, help="YYYYMMDD")
    p.add_argument("--snapshot-manifest", required=False)
    p.add_argument("--calendar", default="data/krx_market_calendar_2025_2029.json")
    p.add_argument("--implementation-sha", default="UNKNOWN")
    p.add_argument("--output", default="outputs/forward_etf_shadow")
    p.add_argument("--self-test", action="store_true")
    return p.parse_args()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_hash(obj: dict) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def read_calendar(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("market") != "KRX":
        raise RuntimeError(f"unexpected calendar market: {data.get('market')}")
    holidays = set(str(x).replace("-", "") for x in data.get("holidays", []))
    return data, holidays


def ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def scheduled_session(d: date, holidays: set[str]) -> bool:
    return d.weekday() < 5 and ymd(d) not in holidays


def scheduled_sessions_between(start: date, end: date, holidays: set[str]):
    out = []
    d = start
    while d <= end:
        if scheduled_session(d, holidays):
            out.append(ymd(d))
        d += timedelta(days=1)
    return out


def last_scheduled_session_of_month(period: pd.Period, holidays: set[str]) -> str:
    start = period.start_time.date()
    end = period.end_time.date()
    sessions = scheduled_sessions_between(start, end, holidays)
    if not sessions:
        raise RuntimeError(f"calendar contains no scheduled KRX session for {period}")
    return sessions[-1]


def next_scheduled_session(signal_date: str, holidays: set[str]) -> str:
    d = datetime.strptime(signal_date, "%Y%m%d").date() + timedelta(days=1)
    for _ in range(20):
        if scheduled_session(d, holidays):
            return ymd(d)
        d += timedelta(days=1)
    raise RuntimeError(f"could not find next scheduled KRX session after {signal_date}")


def actual_trading_dates(db: Path, end_date: str):
    with sqlite3.connect(db) as con:
        x = pd.read_sql_query(
            "SELECT DISTINCT date FROM daily_prices WHERE date BETWEEN ? AND ? ORDER BY date",
            con,
            params=[ANCHOR_DATE, end_date],
        )
    dates = x["date"].astype(str).tolist()
    if not dates or dates[0] != ANCHOR_DATE:
        raise RuntimeError(f"84d anchor missing: first={dates[0] if dates else None}, expected={ANCHOR_DATE}")
    return dates


def cadence_dates(dates: list[str]):
    return dates[::CADENCE]


def first_forward_control(schedule: list[str]):
    candidates = [d for d in schedule if d > FREEZE_DATE]
    return candidates[0] if candidates else None


def snapshot_manifest(path: Path, db: Path, signal_date: str):
    m = json.loads(path.read_text(encoding="utf-8"))
    for key in (
        "research_id", "signal_date", "method_alphakrx_sha", "data_alphakrx_sha",
        "marcap_sha", "db_sha256", "max_price_date", "max_financial_available_date",
    ):
        if key not in m:
            raise RuntimeError(f"snapshot manifest missing {key}")
    if m["research_id"] != RESEARCH_ID:
        raise RuntimeError(f"manifest research ID drift: {m['research_id']}")
    if m["signal_date"] != signal_date or str(m["max_price_date"]) != signal_date:
        raise RuntimeError(
            f"manifest/data date mismatch: signal={signal_date}, manifest={m['signal_date']}, max={m['max_price_date']}"
        )
    if m["method_alphakrx_sha"] != METHOD_ALPHAKRX_SHA:
        raise RuntimeError(f"frozen AlphaKRX method drift: {m['method_alphakrx_sha']}")
    if str(m["max_financial_available_date"]) > signal_date:
        raise RuntimeError("manifest contains future financial availability")
    actual_db_sha = sha256_file(db)
    if actual_db_sha != m["db_sha256"]:
        raise RuntimeError(f"DB SHA mismatch: {actual_db_sha} != {m['db_sha256']}")
    return m


def fetch_etf_prices(signal_date: str, out: Path):
    installed = getattr(fdr, "__version__", None)
    if installed and installed != FDR_VERSION:
        raise RuntimeError(f"FinanceDataReader version drift: {installed} != {FDR_VERSION}")

    start = (pd.Timestamp(signal_date) - pd.Timedelta(days=500)).strftime("%Y-%m-%d")
    end_iso = pd.Timestamp(signal_date).strftime("%Y-%m-%d")
    frames = {}
    provenance = {}
    for code in CODES:
        df = fdr.DataReader(f"NAVER:{code}", start, end_iso).copy()
        if df.empty:
            raise RuntimeError(f"ETF price data empty: {code}")
        df = df.reset_index()
        if "Date" not in df.columns:
            df = df.rename(columns={df.columns[0]: "Date"})
        df["date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y%m%d")
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = (
            df.dropna(subset=["date", "Close"])
            .sort_values("date")
            .drop_duplicates("date")
            [["date", "Open", "High", "Low", "Close", "Volume"]]
            .reset_index(drop=True)
        )
        if df.empty or str(df["date"].max()) != signal_date:
            raise RuntimeError(
                f"ETF source stale on event date {signal_date}: {code} max={None if df.empty else df['date'].max()}"
            )
        move = df["Close"].pct_change().abs()
        if bool((move > MAX_ABS_ETF_MOVE + 1e-12).any()):
            raise RuntimeError(f"ETF >30% one-day move integrity failure: {code}, max={move.max()}")
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        p = out / f"etf_{code}_{signal_date}.csv"
        p.write_bytes(csv_bytes)
        provenance[code] = {
            "label": CODE_LABELS[code],
            "rows": int(len(df)),
            "date_min": str(df["date"].min()),
            "date_max": str(df["date"].max()),
            "max_abs_daily_move": float(move.max(skipna=True)),
            "normalized_csv_sha256": sha256_bytes(csv_bytes),
        }
        frames[code] = df
    return frames, provenance


def common_close_frame(frames: dict[str, pd.DataFrame]):
    close = None
    for code in CODES:
        x = frames[code].set_index("date")[["Close"]].rename(columns={"Close": code})
        close = x if close is None else close.join(x, how="outer")
    if close is None:
        raise RuntimeError("failed to construct ETF close frame")
    return close.sort_index()


def completed_monthly_states(close: pd.DataFrame, signal_date: str, holidays: set[str]):
    common = close[CODES].dropna(how="any").copy()
    common["_dt"] = pd.to_datetime(common.index, format="%Y%m%d", errors="coerce")
    common = common.dropna(subset=["_dt"])
    common["_month"] = common["_dt"].dt.to_period("M")
    tails = common.groupby("_month", sort=True).tail(1).sort_values("_dt").copy()

    # A truncated current month must never be mistaken for a completed month-end.
    keep = []
    for idx, row in tails.iterrows():
        period = row["_month"]
        expected_last = last_scheduled_session_of_month(period, holidays)
        keep.append(str(idx) == expected_last and expected_last <= signal_date)
    monthly = tails.loc[keep].copy()
    if monthly.empty:
        raise RuntimeError("no completed monthly ETF observations")

    for code in CODES:
        monthly[f"{code}_sma10"] = monthly[code].rolling(SMA_MONTHS, min_periods=SMA_MONTHS).mean()
        monthly[f"{code}_trend_on"] = monthly[code] > monthly[f"{code}_sma10"]

    valid = monthly.dropna(subset=[f"{c}_sma10" for c in CODES]).copy()
    if valid.empty:
        raise RuntimeError("insufficient completed month-end history for frozen 10M rule")
    return monthly, valid


def trend_state_from_valid_months(valid: pd.DataFrame):
    row = valid.iloc[-1]
    state_date = row["_dt"].strftime("%Y%m%d")
    legs = {}
    for code in CODES:
        legs[code] = {
            "label": CODE_LABELS[code],
            "month_end_close": float(row[code]),
            "sma10_including_current_month": float(row[f"{code}_sma10"]),
            "trend_on": bool(row[f"{code}_trend_on"]),
        }
    return state_date, legs


def build_control_weights(method_root: Path, db: Path, signal_date: str):
    signal_year = int(signal_date[:4])
    core_start = (pd.Timestamp(f"{signal_year}0101") - pd.Timedelta(days=420)).strftime("%Y%m%d")
    cfg = rpt.Config(core_start, signal_date, signal_date)
    if cfg.horizon != TARGET_HORIZON or cfg.min_market_cap != 200_000_000_000:
        raise RuntimeError(f"control config drift: horizon={cfg.horizon}, min_cap={cfg.min_market_cap}")

    feature_engineer = _register_corrected_mom36(method_root, db, cfg)
    fe = feature_engineer(str(db))
    try:
        panel = fe._prepare_range_core(
            start_date=core_start,
            end_date=signal_date,
            target_horizon=TARGET_HORIZON,
            min_market_cap=cfg.min_market_cap,
            markets=["kospi", "kosdaq"],
            universe_end_date=signal_date,
        )
    finally:
        try:
            fe.close()
        except Exception:
            pass
    if panel.empty:
        raise RuntimeError("empty forward control panel")

    panel = rpt.add_q5_proxy_fields(panel, db)
    panel = rpt.common_universe(panel).sort_values(["date", "stock_code"]).reset_index(drop=True)
    latest = panel[panel["date"].astype(str).eq(signal_date)].copy()
    if latest.empty:
        raise RuntimeError(f"eligible control universe missing signal date {signal_date}; panel max={panel['date'].max()}")

    split = ep.market_split_weights(panel, signal_date)
    weights = {"226490": float(split["kospi"]), "229200": float(split["kosdaq"])}
    if abs(sum(weights.values()) - 1.0) > 1e-12 or min(weights.values()) <= 0:
        raise RuntimeError(f"invalid control weights: {weights}")

    latest["market_cap"] = pd.to_numeric(latest["market_cap"], errors="coerce")
    audit = {
        "core_start": core_start,
        "eligible_names": int(latest["stock_code"].nunique()),
        "kospi_names": int(latest.loc[latest["market_type"].eq("kospi"), "stock_code"].nunique()),
        "kosdaq_names": int(latest.loc[latest["market_type"].eq("kosdaq"), "stock_code"].nunique()),
        "kospi_market_cap": float(latest.loc[latest["market_type"].eq("kospi"), "market_cap"].sum()),
        "kosdaq_market_cap": float(latest.loc[latest["market_type"].eq("kosdaq"), "market_cap"].sum()),
    }
    return weights, audit


def markdown_result(result: dict):
    lines = [
        f"### Forward ETF shadow signal — {result['signal_date']}",
        "",
        f"- RL-ID: `{RESEARCH_ID}`",
        f"- status: **{result['status']}**",
        f"- event types: **{', '.join(result.get('event_types') or ['none'])}**",
        f"- expected T+1: **{result.get('expected_execution_date')}**",
        f"- signal JSON SHA256: `{result.get('signal_sha256')}`",
    ]
    control = result.get("control")
    if control:
        lines += [
            "",
            "#### Frozen 84d control weights",
            f"- KODEX KOSPI 226490: **{control['weights']['226490']:.6%}**",
            f"- KODEX KOSDAQ150 229200: **{control['weights']['229200']:.6%}**",
            f"- eligible names: **{control['audit']['eligible_names']}**",
        ]
    trend = result.get("trend_state")
    if trend:
        lines += ["", f"#### Frozen 10M trend state — completed month-end {trend['state_date']}"]
        for code in CODES:
            leg = trend["legs"][code]
            lines.append(
                f"- {code}: **{'ON' if leg['trend_on'] else 'OFF'}** — "
                f"close {leg['month_end_close']:.4f}, SMA10 {leg['sma10_including_current_month']:.4f}"
            )
    lines += [
        "",
        f"- DB SHA256: `{result['provenance']['db_sha256']}`",
        f"- marcap snapshot: `{result['provenance']['marcap_sha']}`",
        f"- financial raw snapshot: `{result['provenance']['data_alphakrx_sha']}`",
        f"- frozen method AlphaKRX: `{result['provenance']['method_alphakrx_sha']}`",
        "",
        "> Forward primitive only. No performance decision is made here.",
    ]
    return "\n".join(lines) + "\n"


def run_self_test(calendar_path: Path):
    _, holidays = read_calendar(calendar_path)
    assert last_scheduled_session_of_month(pd.Period("2026-11", freq="M"), holidays) == "20261130"
    assert last_scheduled_session_of_month(pd.Period("2026-12", freq="M"), holidays) == "20261230"
    synthetic = [f"D{i:03d}" for i in range(253)]
    assert cadence_dates(synthetic) == ["D000", "D084", "D168", "D252"]

    idx = pd.date_range("2025-01-31", periods=10, freq="ME")
    x = pd.DataFrame({"_dt": idx, "226490": np.arange(1.0, 11.0), "229200": np.arange(2.0, 12.0)})
    for code in CODES:
        x[f"{code}_sma10"] = x[code].rolling(10, min_periods=10).mean()
        x[f"{code}_trend_on"] = x[code] > x[f"{code}_sma10"]
    assert float(x.iloc[-1]["226490_sma10"]) == 5.5
    assert bool(x.iloc[-1]["226490_trend_on"]) is True
    print("forward_etf_shadow_self_test=PASS")


def main():
    a = parse_args()
    calendar_path = Path(a.calendar).resolve()
    if a.self_test:
        run_self_test(calendar_path)
        return

    for name, value in (
        ("--method-alphakrx-root", a.method_alphakrx_root),
        ("--db", a.db),
        ("--signal-date", a.signal_date),
        ("--snapshot-manifest", a.snapshot_manifest),
    ):
        if not value:
            raise ValueError(f"{name} is required unless --self-test is used")
    if len(a.signal_date) != 8 or not a.signal_date.isdigit():
        raise ValueError("--signal-date must be YYYYMMDD")

    method_root = Path(a.method_alphakrx_root).resolve()
    db = Path(a.db).resolve()
    manifest_path = Path(a.snapshot_manifest).resolve()
    out = Path(a.output).resolve()
    out.mkdir(parents=True, exist_ok=True)

    cal_meta, holidays = read_calendar(calendar_path)
    cal_sha = sha256_file(calendar_path)
    manifest = snapshot_manifest(manifest_path, db, a.signal_date)

    dates = actual_trading_dates(db, a.signal_date)
    schedule = cadence_dates(dates)
    first_forward = first_forward_control(schedule)
    control_due = a.signal_date in schedule and a.signal_date > FREEZE_DATE
    forward_started = first_forward is not None and a.signal_date >= first_forward

    period = pd.Period(pd.Timestamp(a.signal_date), freq="M")
    expected_month_end = last_scheduled_session_of_month(period, holidays)
    month_end_due = forward_started and a.signal_date == expected_month_end

    event_types = []
    if control_due:
        event_types.append("control_84d")
    if month_end_due:
        event_types.append("trend_month_end")

    # Before the first post-freeze 84d control, trend observations are warm-up only.
    if not event_types:
        result = {
            "research_id": RESEARCH_ID,
            "signal_date": a.signal_date,
            "status": "NO_EVENT",
            "event_types": [],
            "first_forward_control_seen": first_forward,
            "forward_started": bool(forward_started),
            "expected_month_end": expected_month_end,
            "provenance": {
                "implementation_sha": a.implementation_sha,
                "calendar_sha256": cal_sha,
                "calendar_version": cal_meta.get("version"),
                "db_sha256": manifest["db_sha256"],
                "method_alphakrx_sha": manifest["method_alphakrx_sha"],
                "data_alphakrx_sha": manifest["data_alphakrx_sha"],
                "marcap_sha": manifest["marcap_sha"],
            },
        }
        result["signal_sha256"] = canonical_hash(result)
        (out / f"signal_{a.signal_date}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # The expected date is a regression check only.  Actual DB trading-session
    # cadence is authoritative if KRX closures change.
    if control_due and first_forward == a.signal_date and a.signal_date != EXPECTED_FIRST_FORWARD_CONTROL:
        print(
            f"[calendar-drift] first actual forward control is {a.signal_date}; "
            f"frozen calendar expectation was {EXPECTED_FIRST_FORWARD_CONTROL}",
            flush=True,
        )

    frames, etf_provenance = fetch_etf_prices(a.signal_date, out)
    close = common_close_frame(frames)
    _, valid_months = completed_monthly_states(close, a.signal_date, holidays)
    trend_date, trend_legs = trend_state_from_valid_months(valid_months)

    # On a month-end event the state must be that month. On an 84d event inside
    # a month, the most recent *completed* month initializes the trend sleeve.
    if month_end_due and trend_date != a.signal_date:
        raise RuntimeError(f"month-end trend state stale: {trend_date} != {a.signal_date}")
    if trend_date > a.signal_date:
        raise RuntimeError(f"future trend state detected: {trend_date}")

    control = None
    if control_due:
        weights, control_audit = build_control_weights(method_root, db, a.signal_date)
        control = {"weights": weights, "audit": control_audit}

    result = {
        "research_id": RESEARCH_ID,
        "prereg_comment_id": PREREG_COMMENT_ID,
        "implementation_freeze_comment_id": IMPLEMENTATION_FREEZE_COMMENT_ID,
        "signal_date": a.signal_date,
        "status": "FORWARD_EVENT_FROZEN",
        "event_types": event_types,
        "expected_execution_date": next_scheduled_session(a.signal_date, holidays),
        "first_forward_control_seen": first_forward,
        "cadence": {"anchor": ANCHOR_DATE, "trading_sessions": CADENCE, "actual_dates_authoritative": True},
        "control": control,
        "trend_state": {
            "state_date": trend_date,
            "sma_months": SMA_MONTHS,
            "rolling_mean_includes_current_completed_month": True,
            "legs": trend_legs,
            "off_sleeve_to_cash": True,
            "renormalize_remaining_on_sleeve": False,
            "cash_return_assumption": 0.0,
        },
        "cost_model": {"buy": BUY_COST, "sell": SELL_COST},
        "provenance": {
            "implementation_sha": a.implementation_sha,
            "calendar_sha256": cal_sha,
            "calendar_version": cal_meta.get("version"),
            "db_sha256": manifest["db_sha256"],
            "db_bytes": manifest.get("db_bytes"),
            "max_price_date": manifest["max_price_date"],
            "max_financial_available_date": manifest["max_financial_available_date"],
            "method_alphakrx_sha": manifest["method_alphakrx_sha"],
            "data_alphakrx_sha": manifest["data_alphakrx_sha"],
            "marcap_sha": manifest["marcap_sha"],
            "etf_price_source": "FinanceDataReader NAVER",
            "finance_datareader_version": FDR_VERSION,
            "etf_data": etf_provenance,
        },
    }
    result["signal_sha256"] = canonical_hash(result)

    json_path = out / f"signal_{a.signal_date}.json"
    sha_path = out / f"signal_{a.signal_date}.sha256"
    md_path = out / f"signal_{a.signal_date}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sha_path.write_text(f"{result['signal_sha256']}  {json_path.name}\n", encoding="utf-8")
    md_path.write_text(markdown_result(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
