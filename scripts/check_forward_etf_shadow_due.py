#!/usr/bin/env python3
"""Lightweight calendar gate for RL-2026-08-22-ETF-FORWARD-001.

This script never fetches prices, builds a DB, or calculates performance. It only
answers whether a same-day forward freeze *may* be required under the frozen KRX
calendar snapshot. The authoritative runner still verifies actual trading dates
from the same-day market DB before any signal is frozen.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path

RESEARCH_ID = "RL-2026-08-22-ETF-FORWARD-001"
FREEZE_DATE = "20260822"
CONTINUATION_ANCHOR = "20251117"
CADENCE = 84
EXPECTED_FIRST_FORWARD_CONTROL = "20261127"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="YYYYMMDD; defaults to local date supplied by the caller")
    p.add_argument("--calendar", default="data/krx_market_calendar_2025_2029.json")
    p.add_argument("--self-test", action="store_true")
    return p.parse_args()


def ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def parse_ymd(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def read_calendar(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("market") != "KRX":
        raise RuntimeError(f"unexpected calendar market: {data.get('market')}")
    holidays = {str(x).replace("-", "") for x in data.get("holidays", [])}
    start = str(data.get("coverage_from", "")).replace("-", "")
    end = str(data.get("coverage_to", "")).replace("-", "")
    if len(start) != 8 or len(end) != 8:
        raise RuntimeError("calendar coverage metadata missing")
    return data, holidays, start, end


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


def last_scheduled_session_of_month(day: date, holidays: set[str]) -> str:
    if day.month == 12:
        next_month = date(day.year + 1, 1, 1)
    else:
        next_month = date(day.year, day.month + 1, 1)
    d = next_month - timedelta(days=1)
    while d.month == day.month:
        if scheduled_session(d, holidays):
            return ymd(d)
        d -= timedelta(days=1)
    raise RuntimeError(f"no scheduled KRX session in {day.year}-{day.month:02d}")


def next_scheduled_session(day: date, holidays: set[str]) -> str:
    d = day + timedelta(days=1)
    for _ in range(20):
        if scheduled_session(d, holidays):
            return ymd(d)
        d += timedelta(days=1)
    raise RuntimeError(f"could not find next KRX session after {day}")


def calendar_control_schedule(coverage_end: str, holidays: set[str]):
    anchor = parse_ymd(CONTINUATION_ANCHOR)
    end = parse_ymd(coverage_end)
    sessions = scheduled_sessions_between(anchor, end, holidays)
    if not sessions or sessions[0] != CONTINUATION_ANCHOR:
        raise RuntimeError("calendar does not contain the accepted continuation anchor")
    return sessions[::CADENCE]


def evaluate(signal_date: str, calendar_path: Path):
    if len(signal_date) != 8 or not signal_date.isdigit():
        raise ValueError("--date must be YYYYMMDD")
    cal, holidays, coverage_start, coverage_end = read_calendar(calendar_path)
    if signal_date < coverage_start or signal_date > coverage_end:
        raise RuntimeError(
            f"signal date outside frozen calendar coverage: {signal_date} not in {coverage_start}..{coverage_end}"
        )

    day = parse_ymd(signal_date)
    schedule = calendar_control_schedule(coverage_end, holidays)
    first_forward = next((d for d in schedule if d > FREEZE_DATE), None)
    if first_forward is None:
        raise RuntimeError("calendar coverage does not reach the first forward control")

    is_session = scheduled_session(day, holidays)
    control_due = is_session and signal_date in schedule and signal_date > FREEZE_DATE
    forward_started = signal_date >= first_forward
    month_end = last_scheduled_session_of_month(day, holidays)
    month_end_due = is_session and forward_started and signal_date == month_end

    event_types = []
    if control_due:
        event_types.append("control_84d")
    if month_end_due:
        event_types.append("trend_month_end")

    signal_year = int(signal_date[:4])
    feature_start_year = signal_year - 2
    price_start_year = min(feature_start_year, 2025)

    result = {
        "research_id": RESEARCH_ID,
        "signal_date": signal_date,
        "calendar_version": cal.get("version"),
        "calendar_coverage": [coverage_start, coverage_end],
        "scheduled_session": bool(is_session),
        "first_forward_control_expected": first_forward,
        "forward_started_by_calendar": bool(forward_started),
        "expected_month_end": month_end,
        "control_due_by_calendar": bool(control_due),
        "month_end_due_by_calendar": bool(month_end_due),
        "event_types": event_types,
        "heavy_freeze_required": bool(event_types),
        "price_start_year": price_start_year,
        "expected_t1_by_calendar": next_scheduled_session(day, holidays) if is_session else None,
        "authority_note": (
            "calendar gate only; same-day DB actual trading sessions and frozen runner remain authoritative"
        ),
    }
    return result


def run_self_test(calendar_path: Path):
    pre = evaluate("20260825", calendar_path)
    assert pre["heavy_freeze_required"] is False
    assert pre["first_forward_control_expected"] == EXPECTED_FIRST_FORWARD_CONTROL

    first = evaluate(EXPECTED_FIRST_FORWARD_CONTROL, calendar_path)
    assert first["event_types"] == ["control_84d"]
    assert first["expected_month_end"] == "20261130"
    assert first["price_start_year"] == 2024

    month_end = evaluate("20261130", calendar_path)
    assert month_end["event_types"] == ["trend_month_end"]

    dec = evaluate("20261230", calendar_path)
    assert dec["event_types"] == ["trend_month_end"]
    print("forward_due_checker_self_test=PASS")


def main():
    a = parse_args()
    calendar_path = Path(a.calendar).resolve()
    if a.self_test:
        run_self_test(calendar_path)
        return
    if not a.date:
        raise ValueError("--date is required unless --self-test is used")
    print(json.dumps(evaluate(a.date, calendar_path), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
