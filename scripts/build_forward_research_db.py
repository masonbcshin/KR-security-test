#!/usr/bin/env python3
"""Build a point-in-time forward research DB with frozen methodology and dated data snapshots.

Infrastructure for RL-2026-08-22-ETF-FORWARD-001.

Forward integrity rule: this builder is intentionally *not* a historical replay
utility. A valid signal-day snapshot must contain market data through exactly
the requested signal date and must contain no financial record whose
``available_date`` is later than that signal date. If a later data snapshot is
used to reconstruct an old signal, the build fails instead of deleting future
rows and manufacturing a pseudo-PIT history.

Method and data are versioned separately:
- ``--method-alphakrx-root`` is the frozen audited AlphaKRX methodology checkout.
- ``--data-alphakrx-root`` supplies the raw financial ZIP snapshot available on
  the forward signal date.
- ``--marcap-sha`` pins FinanceData/marcap to an exact repository commit.

No strategy score or return is calculated here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

import build_marcap_db as build

RESEARCH_ID = "RL-2026-08-22-ETF-FORWARD-001"
METHOD_ALPHAKRX_SHA = "e773d4243b7a644dd0c525daccebdf062bc389a1"
_REQUIRED_ITEM_CODES = {
    "ifrs_Assets", "ifrs-full_Assets",
    "ifrs_Equity", "ifrs-full_Equity",
    "ifrs_Liabilities", "ifrs-full_Liabilities",
    "ifrs_CashFlowsFromUsedInOperatingActivities",
    "ifrs-full_CashFlowsFromUsedInOperatingActivities",
    "ifrs_ProfitLoss", "ifrs-full_ProfitLoss",
    "ifrs_GrossProfit", "ifrs-full_GrossProfit",
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--method-alphakrx-root", required=True)
    p.add_argument("--data-alphakrx-root", required=True)
    p.add_argument("--method-alphakrx-sha", default=METHOD_ALPHAKRX_SHA)
    p.add_argument("--data-alphakrx-sha", required=True)
    p.add_argument("--marcap-sha", required=True)
    p.add_argument("--signal-date", required=True, help="YYYYMMDD; must equal the market snapshot max date")
    p.add_argument("--db", required=True)
    p.add_argument("--start-year", type=int, default=2011)
    p.add_argument("--financial-start-year", type=int, default=2015)
    p.add_argument("--cache-dir", default=".cache/forward-marcap")
    p.add_argument("--manifest", default="outputs/forward_db/snapshot_manifest.json")
    return p.parse_args()


def _financial_year(path: Path):
    try:
        return int(path.name[:4])
    except (ValueError, TypeError):
        return None


def load_financials(method_root: Path, data_root: Path, db: Path, start_year: int, end_year: int):
    """Run frozen AlphaKRX ETL code against a separately versioned raw-data tree."""
    sys.path.insert(0, str(method_root))
    from etl.financial_etl import FinancialDataLoader

    raw_root = data_root / "data" / "raw_financial"
    if not raw_root.is_dir():
        raise FileNotFoundError(f"raw financial directory missing: {raw_root}")

    original_read = FinancialDataLoader.read_zip_file

    def read_relevant_only(self, zip_path):
        df = original_read(self, zip_path)
        if df.empty or df.shape[1] <= 10:
            return df
        code = df.iloc[:, 10].astype(str).str.strip()
        keep = code.isin(_REQUIRED_ITEM_CODES) | code.str.contains("항목코드", na=False)
        out = df.loc[keep].copy()
        print(f"[financial-forward] {zip_path.name}: {len(df):,} -> {len(out):,} rows", flush=True)
        return out

    FinancialDataLoader.read_zip_file = read_relevant_only
    loader = FinancialDataLoader(str(db), str(raw_root))
    loader.connect()
    loader.create_tables()
    files = sorted(f for f in raw_root.glob("*.zip") if "_CE_" not in f.name)
    files = [
        f for f in files
        if _financial_year(f) is not None and start_year <= _financial_year(f) <= end_year
    ]
    if not files:
        raise RuntimeError(f"no raw financial ZIP files for {start_year}..{end_year}")

    stats = {"files_processed": 0, "total_items": 0, "errors": 0}
    try:
        for i, f in enumerate(files, 1):
            try:
                _, items = loader.process_file(f)
                stats["files_processed"] += 1
                stats["total_items"] += items
            except Exception as exc:
                stats["errors"] += 1
                print(f"[financial-forward] ERROR {f.name}: {exc}", flush=True)
            if i % 10 == 0 or i == len(files):
                print(f"[financial-forward] progress {i}/{len(files)}", flush=True)
        cur = loader.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM financial_periods")
        stats["total_periods"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM financial_items_bs_cf")
        stats["bs_cf_items"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM financial_items_pl")
        stats["pl_items"] = cur.fetchone()[0]
    finally:
        loader.close()
        FinancialDataLoader.read_zip_file = original_read

    if stats["errors"]:
        raise RuntimeError(f"financial ETL had {stats['errors']} errors")
    print(f"[financial-forward] complete {stats}", flush=True)
    return stats


def price_snapshot_status(db: Path, signal_date: str):
    """Require a genuine same-day market snapshot; never trim a later snapshot."""
    with sqlite3.connect(db) as con:
        min_date, max_date, rows = con.execute(
            "SELECT MIN(date), MAX(date), COUNT(*) FROM daily_prices"
        ).fetchone()
    if max_date is None:
        raise RuntimeError("empty market snapshot")
    if str(max_date) != signal_date:
        direction = "future/backfilled" if str(max_date) > signal_date else "stale/incomplete"
        raise RuntimeError(
            f"market snapshot is {direction}: max_date={max_date}, required={signal_date}; "
            "forward signals must not be reconstructed from a later snapshot"
        )
    return {"daily_rows": int(rows), "min_price_date": str(min_date), "max_price_date": str(max_date)}


def sha256_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def max_financial_availability(db: Path):
    with sqlite3.connect(db) as con:
        row = con.execute("SELECT MAX(REPLACE(available_date,'-','')) FROM financial_periods").fetchone()
    return None if not row or row[0] is None else str(row[0])


def guard_financial_snapshot(db: Path, signal_date: str):
    max_available = max_financial_availability(db)
    if max_available is None:
        raise RuntimeError("financial snapshot contains no available_date")
    if max_available > signal_date:
        raise RuntimeError(
            f"future financial availability detected: max_available={max_available}, signal={signal_date}; "
            "do not use a later raw-data snapshot to recreate an old forward signal"
        )
    return max_available


def main():
    a = parse_args()
    if len(a.signal_date) != 8 or not a.signal_date.isdigit():
        raise ValueError("--signal-date must be YYYYMMDD")
    if a.method_alphakrx_sha != METHOD_ALPHAKRX_SHA:
        raise RuntimeError(
            f"methodology drift forbidden: {a.method_alphakrx_sha} != {METHOD_ALPHAKRX_SHA}"
        )

    method_root = Path(a.method_alphakrx_root).resolve()
    data_root = Path(a.data_alphakrx_root).resolve()
    db = Path(a.db).resolve()
    manifest_path = Path(a.manifest).resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    end_year = int(a.signal_date[:4])
    # Cache is namespaced by the exact market-data commit. Reusing a yearly
    # parquet from an older marcap commit would silently make a later forward
    # signal stale even though --marcap-sha changed.
    cache = (Path(a.cache_dir).resolve() / a.marcap_sha)

    # Pin market data to the run-time FinanceData/marcap commit.
    build.MARCAP_RAW = f"https://raw.githubusercontent.com/FinanceData/marcap/{a.marcap_sha}/data/marcap-{{year}}.parquet"

    print(f"[forward-db] build prices {a.start_year}..{end_year} @ marcap {a.marcap_sha}", flush=True)
    build.build_prices(db, cache, a.start_year, end_year)
    price_status = price_snapshot_status(db, a.signal_date)

    print(
        f"[forward-db] load PIT financials {a.financial_start_year}..{end_year} "
        f"method={a.method_alphakrx_sha} data={a.data_alphakrx_sha}",
        flush=True,
    )
    fin = load_financials(method_root, data_root, db, a.financial_start_year, end_year)
    max_fin_available = guard_financial_snapshot(db, a.signal_date)

    print("[forward-db] build adjusted prices with frozen method code", flush=True)
    build.build_adjusted_prices(method_root, db)
    audit = build.audit(db)
    if str(audit["date_max"]) != a.signal_date:
        raise RuntimeError(f"post-adjustment date drift: {audit['date_max']} != {a.signal_date}")

    db_sha = sha256_file(db)
    manifest = {
        "research_id": RESEARCH_ID,
        "signal_date": a.signal_date,
        "method_alphakrx_sha": a.method_alphakrx_sha,
        "data_alphakrx_sha": a.data_alphakrx_sha,
        "marcap_sha": a.marcap_sha,
        "marcap_cache_namespace": str(cache),
        "db_sha256": db_sha,
        "db_bytes": db.stat().st_size,
        "max_price_date": audit["date_max"],
        "max_financial_available_date": max_fin_available,
        "price_snapshot": price_status,
        "financial_etl": fin,
        "audit": audit,
        "replay_policy": "same-day snapshot only; future/stale market data or future financial availability => FAIL",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
