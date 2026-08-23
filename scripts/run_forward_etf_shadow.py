#!/usr/bin/env python3
"""Authoritative entrypoint for RL-2026-08-22-ETF-FORWARD-001.

This wrapper adds operational guards without changing either frozen strategy:

1. continue the accepted 84-session schedule from the immutable artifact's last
   verified signal (2025-11-17), while retaining the original 2018-01-02
   research anchor in strategy metadata;
2. reject forward signal freezing when PIT financial availability is more than
   180 calendar days stale versus the signal-day market snapshot; and
3. persist the schedule/data/implementation preflight provenance before the
   strategy engine emits a forward signal primitive.

Using the accepted last signal as a continuation anchor is mathematically the
same 84-session sequence as rebuilding the entire 2018-present trading calendar,
but lets the signal-day research DB retain only the price history actually
needed for feature warm-up plus the fixed continuation anchor.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

import generate_forward_etf_shadow_signal as engine

RESEARCH_ID = "RL-2026-08-22-ETF-FORWARD-001"
SCHEDULE_PROOF = Path("data/accepted_84d_control_schedule.json")
EXPECTED_DATES_SHA256 = "dc5c6a140550a663f9349e27ead727ab0f3e6f5121e008a4b45c4c69223b15e4"
ORIGINAL_ANCHOR = "20180102"
CONTINUATION_ANCHOR = "20251117"
CADENCE = 84
MAX_FINANCIAL_STALENESS_DAYS = 180


def _arg_value(flag: str):
    try:
        i = sys.argv.index(flag)
    except ValueError:
        return None
    if i + 1 >= len(sys.argv):
        raise ValueError(f"{flag} requires a value")
    return sys.argv[i + 1]


def _dates_digest(dates: list[str]) -> str:
    payload = ("\n".join(dates) + "\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_hash(obj: dict) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_schedule_proof(path: Path = SCHEDULE_PROOF):
    proof = json.loads(path.read_text(encoding="utf-8"))
    dates = [str(x) for x in proof.get("signal_dates") or []]
    checks = {
        "cadence": int(proof.get("cadence_trading_sessions", -1)) == CADENCE,
        "original_anchor": proof.get("original_anchor") == ORIGINAL_ANCHOR,
        "accepted_last_signal": proof.get("accepted_last_signal") == CONTINUATION_ANCHOR,
        "first_date": bool(dates) and dates[0] == ORIGINAL_ANCHOR,
        "last_date": bool(dates) and dates[-1] == CONTINUATION_ANCHOR,
        "n_dates": len(dates) == 24,
        "dates_sha": _dates_digest(dates) == EXPECTED_DATES_SHA256,
        "declared_dates_sha": proof.get("unique_signal_dates_sha256") == EXPECTED_DATES_SHA256,
    }
    if not all(checks.values()):
        raise RuntimeError(f"accepted 84d schedule proof drift: {checks}")
    return proof


def validate_implementation_sha(value: str | None):
    if not value or not re.fullmatch(r"[0-9a-fA-F]{40}", value):
        raise RuntimeError(
            "--implementation-sha must be the exact 40-hex commit checked out for this forward run"
        )
    value = value.lower()

    # In the intended GitHub execution path this is a detached checkout of the
    # frozen implementation.  Manual/exported environments may not have .git;
    # they still must provide an exact-looking SHA, but cannot claim the local
    # checkout comparison below.
    try:
        actual = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip().lower()
    except (FileNotFoundError, subprocess.CalledProcessError):
        actual = None
    if actual and actual != value:
        raise RuntimeError(f"implementation checkout drift: git HEAD {actual} != supplied {value}")
    return value, actual


def continuation_trading_dates(db: Path, end_date: str):
    """Actual KRX sessions from the immutable accepted last 84d signal onward."""
    if end_date < CONTINUATION_ANCHOR:
        raise RuntimeError(
            f"forward DB ends before accepted continuation anchor: {end_date} < {CONTINUATION_ANCHOR}"
        )
    with sqlite3.connect(db) as con:
        x = pd.read_sql_query(
            "SELECT DISTINCT date FROM daily_prices WHERE date BETWEEN ? AND ? ORDER BY date",
            con,
            params=[CONTINUATION_ANCHOR, end_date],
        )
    dates = x["date"].astype(str).tolist()
    if not dates or dates[0] != CONTINUATION_ANCHOR:
        raise RuntimeError(
            f"accepted continuation anchor missing from forward DB: "
            f"first={dates[0] if dates else None}, expected={CONTINUATION_ANCHOR}"
        )
    return dates


def preflight(
    db: Path,
    signal_date: str,
    manifest_path: Path,
    implementation_sha: str,
):
    proof = validate_schedule_proof()
    proof_file_sha = hashlib.sha256(SCHEDULE_PROOF.read_bytes()).hexdigest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("research_id") != RESEARCH_ID:
        raise RuntimeError(f"manifest RL-ID drift: {manifest.get('research_id')}")
    if str(manifest.get("signal_date")) != signal_date:
        raise RuntimeError(
            f"manifest signal date drift: {manifest.get('signal_date')} != {signal_date}"
        )

    with sqlite3.connect(db) as con:
        market_max = con.execute("SELECT MAX(date) FROM daily_prices").fetchone()[0]
        fin_max = con.execute(
            "SELECT MAX(REPLACE(available_date,'-','')) FROM financial_periods"
        ).fetchone()[0]
    market_max = None if market_max is None else str(market_max)
    fin_max = None if fin_max is None else str(fin_max)
    if market_max != signal_date:
        raise RuntimeError(f"forward market snapshot not same-day: {market_max} != {signal_date}")
    if not fin_max:
        raise RuntimeError("forward DB has no financial available_date")
    if fin_max > signal_date:
        raise RuntimeError(f"future financial availability: {fin_max} > {signal_date}")

    age = (
        datetime.strptime(signal_date, "%Y%m%d")
        - datetime.strptime(fin_max, "%Y%m%d")
    ).days
    if age > MAX_FINANCIAL_STALENESS_DAYS:
        raise RuntimeError(
            f"DATA_NOT_READY: PIT financial snapshot is {age} calendar days stale; "
            f"max allowed={MAX_FINANCIAL_STALENESS_DAYS}, fin_max={fin_max}, signal={signal_date}"
        )

    dates = continuation_trading_dates(db, signal_date)
    schedule = dates[::CADENCE]
    first_forward = next((d for d in schedule if d > engine.FREEZE_DATE), None)
    control_due = signal_date in schedule and signal_date > engine.FREEZE_DATE

    result = {
        "research_id": RESEARCH_ID,
        "signal_date": signal_date,
        "implementation_sha": implementation_sha,
        "accepted_schedule_proof_file_sha256": proof_file_sha,
        "accepted_schedule_dates_sha256": EXPECTED_DATES_SHA256,
        "accepted_schedule_source_run": proof.get("source_run_id"),
        "accepted_schedule_source_artifact": proof.get("source_artifact_id"),
        "accepted_schedule_source_artifact_digest": proof.get("source_artifact_digest"),
        "accepted_schedule_source_member_sha256": proof.get("source_member_sha256"),
        "original_anchor": ORIGINAL_ANCHOR,
        "continuation_anchor": CONTINUATION_ANCHOR,
        "cadence_sessions": CADENCE,
        "db_sha256": manifest.get("db_sha256"),
        "method_alphakrx_sha": manifest.get("method_alphakrx_sha"),
        "data_alphakrx_sha": manifest.get("data_alphakrx_sha"),
        "marcap_sha": manifest.get("marcap_sha"),
        "market_max_date": market_max,
        "financial_available_date": fin_max,
        "financial_staleness_calendar_days": age,
        "first_post_freeze_control_seen": first_forward,
        "control_due": control_due,
        "schedule_tail": schedule[-5:],
    }
    result["canonical_payload_sha256"] = _canonical_hash(result)
    print("forward_shadow_preflight=PASS")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def persist_preflight(out: Path, signal_date: str, result: dict):
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"preflight_{signal_date}.json"
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    file_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    (out / f"preflight_{signal_date}.sha256").write_text(
        f"{file_sha}  {path.name}\n", encoding="utf-8"
    )
    return path, file_sha


def main():
    # Always verify the immutable schedule proof, including in pure self-test mode.
    validate_schedule_proof()

    # The engine's strategy metadata retains ORIGINAL_ANCHOR=20180102. Only its
    # runtime trading-date source is replaced with the equivalent continuation
    # calendar so a compact forward DB does not need 2018-present prices.
    engine.actual_trading_dates = continuation_trading_dates

    if "--self-test" in sys.argv:
        engine.main()
        return

    db_arg = _arg_value("--db")
    signal_date = _arg_value("--signal-date")
    manifest_arg = _arg_value("--snapshot-manifest")
    implementation_arg = _arg_value("--implementation-sha")
    output_arg = _arg_value("--output") or "outputs/forward_etf_shadow"
    if not db_arg or not signal_date or not manifest_arg:
        raise ValueError("--db, --signal-date and --snapshot-manifest are required")

    implementation_sha, _ = validate_implementation_sha(implementation_arg)
    result = preflight(
        Path(db_arg).resolve(),
        signal_date,
        Path(manifest_arg).resolve(),
        implementation_sha,
    )
    path, file_sha = persist_preflight(Path(output_arg).resolve(), signal_date, result)
    print(f"forward_preflight_artifact={path} sha256={file_sha}")

    # Strategy engine executes only after the immutable schedule/data/code
    # provenance has been persisted successfully.
    engine.main()


if __name__ == "__main__":
    main()
