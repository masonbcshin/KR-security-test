#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--output-dir", default="outputs/marcap_audit")
    return p.parse_args()


def fetchall_dict(con: sqlite3.Connection, sql: str, params=()):
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    a = parse_args()
    db = Path(a.db)
    out = Path(a.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db) as con:
        samsung_top = fetchall_dict(
            con,
            """
            WITH daily_totals AS (
              SELECT date, SUM(market_cap) AS total_market_cap,
                     MAX(market_cap) AS max_market_cap
              FROM daily_prices
              WHERE market_cap > 0
              GROUP BY date
            )
            SELECT p.date, p.closing_price, p.market_cap,
                   CASE WHEN p.closing_price > 0 THEN p.market_cap / p.closing_price END AS implied_shares,
                   t.total_market_cap,
                   CASE WHEN t.total_market_cap > 0 THEN p.market_cap / t.total_market_cap END AS market_weight,
                   t.max_market_cap
            FROM daily_prices p
            JOIN daily_totals t USING(date)
            WHERE p.stock_code='005930'
            ORDER BY p.market_cap DESC
            LIMIT 100
            """,
        )

        samsung_by_year = fetchall_dict(
            con,
            """
            WITH s AS (
              SELECT substr(date,1,4) AS year, date, closing_price, market_cap,
                     CASE WHEN closing_price > 0 THEN market_cap / closing_price END AS implied_shares,
                     ROW_NUMBER() OVER (
                       PARTITION BY substr(date,1,4)
                       ORDER BY market_cap DESC
                     ) AS rn
              FROM daily_prices
              WHERE stock_code='005930'
            )
            SELECT year, date, closing_price, market_cap, implied_shares
            FROM s WHERE rn=1 ORDER BY year
            """,
        )

        daily_market = fetchall_dict(
            con,
            """
            SELECT date,
                   SUM(market_cap) AS total_market_cap,
                   MAX(market_cap) AS largest_company_cap,
                   MAX(market_cap) / NULLIF(SUM(market_cap),0) AS largest_company_weight,
                   COUNT(*) AS names
            FROM daily_prices
            WHERE market_cap > 0
            GROUP BY date
            ORDER BY largest_company_weight DESC
            LIMIT 100
            """,
        )

        extreme_rows = fetchall_dict(
            con,
            """
            SELECT stock_code, date, closing_price, market_cap,
                   CASE WHEN closing_price > 0 THEN market_cap / closing_price END AS implied_shares,
                   market_type
            FROM daily_prices
            WHERE market_cap >= 1e15
            ORDER BY market_cap DESC
            LIMIT 500
            """,
        )

        summary = {
            "db": str(db),
            "samsung_max_market_cap": samsung_top[0] if samsung_top else None,
            "samsung_rows_over_1q_krw": con.execute(
                "SELECT COUNT(*) FROM daily_prices WHERE stock_code='005930' AND market_cap >= 1e15"
            ).fetchone()[0],
            "all_rows_over_1q_krw": con.execute(
                "SELECT COUNT(*) FROM daily_prices WHERE market_cap >= 1e15"
            ).fetchone()[0],
            "dates_with_largest_company_weight_over_50pct": con.execute(
                """
                SELECT COUNT(*) FROM (
                  SELECT date, MAX(market_cap) / NULLIF(SUM(market_cap),0) AS w
                  FROM daily_prices WHERE market_cap > 0 GROUP BY date
                ) WHERE w > 0.5
                """
            ).fetchone()[0],
            "date_min": con.execute("SELECT MIN(date) FROM daily_prices").fetchone()[0],
            "date_max": con.execute("SELECT MAX(date) FROM daily_prices").fetchone()[0],
        }

    write_csv(out / "samsung_top100.csv", samsung_top)
    write_csv(out / "samsung_yearly_max.csv", samsung_by_year)
    write_csv(out / "daily_market_extremes.csv", daily_market)
    write_csv(out / "all_caps_over_1q.csv", extreme_rows)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
