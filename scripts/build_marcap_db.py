#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

MARCAP_RAW = "https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--alphakrx-root", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--start-year", type=int, required=True)
    p.add_argument("--end-year", type=int, required=True)
    p.add_argument("--cache-dir", default=".cache/marcap")
    return p.parse_args()


def download(url: str, dest: Path):
    if dest.exists() and dest.stat().st_size > 1000:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with tmp.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
        tmp.replace(dest)


def pick_col(df: pd.DataFrame, names: list[str], required=True):
    for n in names:
        if n in df.columns:
            return n
    if required:
        raise KeyError(f"none of columns found: {names}; got={list(df.columns)}")
    return None


def normalize_year(df: pd.DataFrame) -> pd.DataFrame:
    date_col = pick_col(df, ["Date", "date"])
    code_col = pick_col(df, ["Code", "code"])
    name_col = pick_col(df, ["Name", "name"])
    open_col = pick_col(df, ["Open", "open"])
    high_col = pick_col(df, ["High", "high"])
    low_col = pick_col(df, ["Low", "low"])
    close_col = pick_col(df, ["Close", "close"])
    volume_col = pick_col(df, ["Volume", "volume"])
    amount_col = pick_col(df, ["Amount", "amount"])
    mcap_col = pick_col(df, ["Marcap", "MarketCap", "market_cap"])
    shares_col = pick_col(df, ["Stocks", "Shares", "shares"])
    market_col = pick_col(df, ["Market", "market"])
    change_col = pick_col(df, ["ChagesRatio", "ChangesRatio", "ChangeRatio", "Change"], required=False)

    out = pd.DataFrame({
        "stock_code": df[code_col].astype(str).str.extract(r"(\d{6})", expand=False),
        "date": pd.to_datetime(df[date_col]).dt.strftime("%Y%m%d"),
        "current_name": df[name_col].astype(str),
        "opening_price": pd.to_numeric(df[open_col], errors="coerce"),
        "high_price": pd.to_numeric(df[high_col], errors="coerce"),
        "low_price": pd.to_numeric(df[low_col], errors="coerce"),
        "closing_price": pd.to_numeric(df[close_col], errors="coerce"),
        "volume": pd.to_numeric(df[volume_col], errors="coerce"),
        "value": pd.to_numeric(df[amount_col], errors="coerce"),
        "market_cap": pd.to_numeric(df[mcap_col], errors="coerce"),
        "shares_outstanding": pd.to_numeric(df[shares_col], errors="coerce"),
        "market_raw": df[market_col].astype(str).str.upper(),
    })
    out["market_type"] = out["market_raw"].map({"KOSPI": "kospi", "KOSDAQ": "kosdaq"})
    out = out[out["market_type"].notna()].copy()

    if change_col:
        out["change_rate"] = pd.to_numeric(df.loc[out.index, change_col], errors="coerce")
    else:
        out = out.sort_values(["stock_code", "date"])
        out["change_rate"] = out.groupby("stock_code")["closing_price"].pct_change() * 100.0

    top_mcap = out["market_cap"].quantile(0.999)
    if pd.notna(top_mcap) and top_mcap < 1e13:
        out["market_cap"] *= 1_000_000.0

    cols = [
        "stock_code", "date", "current_name", "market_type",
        "opening_price", "high_price", "low_price", "closing_price",
        "volume", "value", "market_cap", "shares_outstanding", "change_rate",
    ]
    out = out[cols].dropna(subset=["stock_code", "date", "closing_price", "market_cap"])
    out = out[out["stock_code"].str.fullmatch(r"\d{6}")]
    return out


def create_base_schema(conn: sqlite3.Connection):
    conn.executescript("""
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=NORMAL;
    CREATE TABLE IF NOT EXISTS daily_prices (
      stock_code TEXT NOT NULL,
      date TEXT NOT NULL,
      closing_price REAL,
      opening_price REAL,
      high_price REAL,
      low_price REAL,
      volume REAL,
      value REAL,
      market_cap REAL,
      change REAL,
      change_rate REAL,
      market_type TEXT NOT NULL,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(stock_code, date)
    );
    CREATE TABLE IF NOT EXISTS stocks (
      stock_code TEXT PRIMARY KEY,
      current_name TEXT NOT NULL,
      current_market_type TEXT,
      current_sector_type TEXT,
      shares_outstanding INTEGER,
      is_active INTEGER NOT NULL DEFAULT 1,
      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS delisted_stocks (
      stock_code TEXT PRIMARY KEY,
      delisting_date TEXT,
      downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_dp_stock_date ON daily_prices(stock_code, date);
    CREATE INDEX IF NOT EXISTS idx_dp_date_mcap ON daily_prices(date, market_cap);
    """)


def insert_year(conn: sqlite3.Connection, x: pd.DataFrame):
    rows = x[[
        "stock_code", "date", "closing_price", "opening_price", "high_price",
        "low_price", "volume", "value", "market_cap", "change_rate", "market_type"
    ]].copy()
    rows["change"] = np.nan
    rows = rows[[
        "stock_code", "date", "closing_price", "opening_price", "high_price",
        "low_price", "volume", "value", "market_cap", "change", "change_rate", "market_type"
    ]]
    # pandas method='multi' expands every cell into one SQL statement and easily
    # exceeds SQLite's host-parameter limit. Default executemany keeps each row
    # parameterized independently and is both safe and fast enough here.
    rows.to_sql("daily_prices", conn, if_exists="append", index=False, chunksize=20_000, method=None)


def rebuild_stock_master(conn: sqlite3.Connection, all_meta: pd.DataFrame):
    m = all_meta.sort_values(["stock_code", "date"]).groupby("stock_code", as_index=False).tail(1).copy()
    max_date = all_meta["date"].max()
    m["is_active"] = (m["date"] >= max_date).astype(int)
    data = m[["stock_code", "current_name", "market_type", "shares_outstanding", "is_active"]].copy()
    data.columns = ["stock_code", "current_name", "current_market_type", "shares_outstanding", "is_active"]
    data["current_sector_type"] = None
    data = data[["stock_code", "current_name", "current_market_type", "current_sector_type", "shares_outstanding", "is_active"]]
    conn.execute("DELETE FROM stocks")
    data.to_sql("stocks", conn, if_exists="append", index=False, chunksize=10_000, method=None)


def load_financials(alphakrx_root: Path, db: Path):
    sys.path.insert(0, str(alphakrx_root))
    from etl.financial_etl import FinancialDataLoader
    raw = alphakrx_root / "data" / "raw_financial"
    loader = FinancialDataLoader(str(db), str(raw))
    loader.connect()
    loader.create_tables()
    try:
        stats = loader.process_all()
    finally:
        loader.close()
    return stats


def build_adjusted_prices(alphakrx_root: Path, db: Path):
    sys.path.insert(0, str(alphakrx_root))
    from etl.adj_price_etl import AdjPriceETL
    AdjPriceETL(str(db)).run(skip_validate=False)


def audit(db: Path) -> dict:
    with sqlite3.connect(db) as con:
        r = {}
        r["daily_rows"] = con.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
        r["stocks"] = con.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]
        r["date_min"], r["date_max"] = con.execute("SELECT MIN(date),MAX(date) FROM daily_prices").fetchone()
        r["financial_periods"] = con.execute("SELECT COUNT(*) FROM financial_periods").fetchone()[0]
        r["adj_rows"] = con.execute("SELECT COUNT(*) FROM adj_daily_prices").fetchone()[0]
        sam = con.execute("""
          SELECT dp.date, dp.closing_price, ap.adj_closing_price, dp.market_cap
          FROM daily_prices dp JOIN adj_daily_prices ap USING(stock_code,date)
          WHERE dp.stock_code='005930' AND dp.date BETWEEN '20180420' AND '20180510'
          ORDER BY dp.date
        """).fetchall()
        r["samsung_split_rows"] = len(sam)
        r["samsung_max_mcap"] = con.execute(
            "SELECT MAX(market_cap) FROM daily_prices WHERE stock_code='005930'"
        ).fetchone()[0]
        if r["samsung_max_mcap"] is None or r["samsung_max_mcap"] < 1e14:
            raise RuntimeError(f"market-cap scale audit failed: {r['samsung_max_mcap']}")
        if r["financial_periods"] < 1000:
            raise RuntimeError(f"financial ETL audit failed: only {r['financial_periods']} periods")
        if r["adj_rows"] != r["daily_rows"]:
            raise RuntimeError(f"adjusted-price row mismatch {r['adj_rows']} vs {r['daily_rows']}")
        return r


def main():
    a = parse_args()
    alphakrx = Path(a.alphakrx_root).resolve()
    db = Path(a.db).resolve()
    cache = Path(a.cache_dir).resolve()
    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()

    meta = []
    with sqlite3.connect(db) as con:
        create_base_schema(con)
        for year in range(a.start_year, a.end_year + 1):
            f = cache / f"marcap-{year}.parquet"
            print(f"[marcap] {year}: download", flush=True)
            download(MARCAP_RAW.format(year=year), f)
            raw = pd.read_parquet(f)
            x = normalize_year(raw)
            print(f"[marcap] {year}: {len(x):,} KOSPI/KOSDAQ rows", flush=True)
            insert_year(con, x)
            meta.append(x[["stock_code", "date", "current_name", "market_type", "shares_outstanding"]])
            con.commit()
        all_meta = pd.concat(meta, ignore_index=True)
        rebuild_stock_master(con, all_meta)
        con.commit()

    print("[financial] load AlphaKRX DART bulk files", flush=True)
    stats = load_financials(alphakrx, db)
    print(f"[financial] {stats}", flush=True)
    print("[adjusted] build adjusted OHLC", flush=True)
    build_adjusted_prices(alphakrx, db)
    result = audit(db)
    Path("outputs").mkdir(exist_ok=True)
    Path("outputs/data_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
