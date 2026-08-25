#!/usr/bin/env python3
"""Generate provisional target holdings for the accepted personal-quant Core.

Frozen production baseline:
- equity sleeve 60%
  - KODEX KOSPI (226490) relative weight = eligible-universe KOSPI market-cap share
  - KODEX KOSDAQ150 (229200) relative weight = eligible-universe KOSDAQ market-cap share
- defensive sleeve 40%
  - KODEX 단기채권PLUS (214980)
- target-weight refresh every 84 actual KRX trading sessions
- cadence sequence originates at the original research first signal, 2018-01-02
- T+1 execution convention

This script is a productionization calculator, not a backtest optimizer. It emits
TARGET holdings only. It contains no brokerage submission path.

A stale PIT-financial feed does not silently pass: outputs are marked
DATA_READY=false / LIVE_READY=false when the latest financial available_date is
too old. The >180-day guard is intentionally retained.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import FinanceDataReader as fdr

import run_portable_tournament as rpt
from run_long_reversal_challenger import _register_corrected_mom36


ETF_CODES = {"kospi": "226490", "kosdaq": "229200", "safe": "214980"}
ETF_LABELS = {
    "226490": "KODEX KOSPI",
    "229200": "KODEX KOSDAQ150",
    "214980": "KODEX 단기채권PLUS",
}
EQUITY_EXPOSURE = 0.60
SAFE_EXPOSURE = 0.40
SCHEDULE_ORIGIN = "20180102"
HISTORICAL_TEST_END = "20260320"
HISTORICAL_84_LAST_SIGNAL = "20251117"
HORIZON = 84
DEFAULT_CAPITALS = [10_000_000.0, 30_000_000.0, 100_000_000.0]
MAX_FINANCIAL_STALENESS_DAYS = 180
MAX_MARKET_STALENESS_DAYS = 7


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--alphakrx-root", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--output", default="outputs/personal_quant_live")
    p.add_argument("--capitals", default=",".join(str(int(x)) for x in DEFAULT_CAPITALS))
    return p.parse_args()


def db_availability(db: Path):
    with sqlite3.connect(db) as con:
        market_max = con.execute("SELECT MAX(date) FROM daily_prices").fetchone()[0]
        fin_max = con.execute("SELECT MAX(REPLACE(available_date,'-','')) FROM financial_periods").fetchone()[0]
    if not market_max:
        raise RuntimeError("daily_prices has no data")
    if not fin_max:
        raise RuntimeError("financial_periods has no available_date")
    return str(market_max), str(fin_max)


def db_trading_dates(db: Path, start: str, end: str):
    with sqlite3.connect(db) as con:
        x = pd.read_sql_query(
            "SELECT DISTINCT date FROM daily_prices WHERE date BETWEEN ? AND ? ORDER BY date",
            con,
            params=[start, end],
        )
    return x["date"].astype(str).tolist()


def next_date_after(dates: list[str], date: str):
    later = [d for d in dates if d > date]
    return later[0] if later else None


def fetch_etf_closes(end_date: str):
    start = (pd.Timestamp(end_date) - pd.Timedelta(days=20)).strftime("%Y-%m-%d")
    end = pd.Timestamp(end_date).strftime("%Y-%m-%d")
    series = {}
    for code in ETF_LABELS:
        x = fdr.DataReader(f"NAVER:{code}", start, end).copy().reset_index()
        if x.empty:
            raise RuntimeError(f"empty ETF data for {code}")
        if "Date" not in x.columns:
            x = x.rename(columns={x.columns[0]: "Date"})
        x["date"] = pd.to_datetime(x["Date"], errors="coerce").dt.strftime("%Y%m%d")
        x["Close"] = pd.to_numeric(x["Close"], errors="coerce")
        x["Volume"] = pd.to_numeric(x["Volume"], errors="coerce")
        x = x[
            (x["date"] <= end_date)
            & np.isfinite(x["Close"])
            & (x["Close"] > 0)
            & (x["Volume"].fillna(0) > 0)
        ]
        if x.empty:
            raise RuntimeError(f"no tradable ETF close <= {end_date} for {code}")
        series[code] = (
            x[["date", "Close"]]
            .drop_duplicates("date", keep="last")
            .set_index("date")["Close"]
        )
    common = sorted(set.intersection(*(set(s.index) for s in series.values())))
    if not common:
        raise RuntimeError("no common ETF price date")
    d = common[-1]
    return d, {code: float(series[code].loc[d]) for code in series}


def target_holdings(capital: float, weights: dict[str, float], prices: dict[str, float], buy_cost: float):
    if abs(sum(weights.values()) - 1.0) > 1e-10:
        raise RuntimeError(f"target weights do not sum to 1: {weights}")
    gross_budget = float(capital) / (1.0 + buy_cost)
    rows = []
    invested = 0.0
    for code in [ETF_CODES["kospi"], ETF_CODES["kosdaq"], ETF_CODES["safe"]]:
        w = float(weights[code])
        p = float(prices[code])
        shares = int(np.floor(gross_budget * w / p))
        gross = shares * p
        invested += gross
        rows.append({
            "capital_krw": capital,
            "stock_code": code,
            "label": ETF_LABELS[code],
            "target_weight": w,
            "price": p,
            "target_shares": shares,
            "gross_notional": gross,
        })
    estimated_buy_cost = invested * buy_cost
    residual = capital - invested - estimated_buy_cost
    for r in rows:
        r["estimated_total_buy_cost"] = estimated_buy_cost
        r["portfolio_residual_cash"] = residual
        r["portfolio_residual_cash_ratio"] = residual / capital
    return rows


def main():
    a = parse_args()
    alphakrx = Path(a.alphakrx_root).resolve()
    db = Path(a.db).resolve()
    out = Path(a.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(alphakrx))
    capitals = [float(x.strip()) for x in a.capitals.split(",") if x.strip()]

    market_max, fin_max = db_availability(db)
    market_dt = pd.Timestamp(market_max)
    fin_dt = pd.Timestamp(fin_max)
    market_stale_days = int((pd.Timestamp.today().normalize() - market_dt).days)
    financial_stale_days = int((market_dt - fin_dt).days)

    trading_dates = db_trading_dates(db, SCHEDULE_ORIGIN, market_max)
    if SCHEDULE_ORIGIN not in trading_dates:
        raise RuntimeError(f"schedule origin {SCHEDULE_ORIGIN} missing from DB trading calendar")
    origin_idx = trading_dates.index(SCHEDULE_ORIGIN)
    scheduled_all = trading_dates[origin_idx::HORIZON]
    historical_schedule = [d for d in scheduled_all if d <= HISTORICAL_TEST_END]
    if not historical_schedule or historical_schedule[-1] != HISTORICAL_84_LAST_SIGNAL:
        raise RuntimeError(
            "84-day production calendar does not reproduce the robustness-test schedule: "
            f"expected historical last signal {HISTORICAL_84_LAST_SIGNAL}, got "
            f"{historical_schedule[-1] if historical_schedule else None}"
        )
    latest_signal = scheduled_all[-1]
    execution_date = next_date_after(trading_dates, latest_signal)

    # Keep the original research feature/universe definition (42-day target
    # horizon) while ETF target refresh cadence is independently frozen at 84.
    cfg = rpt.Config("20260101", "20260101", market_max)
    feature_engineer = _register_corrected_mom36(alphakrx, db, cfg)
    fe = feature_engineer(str(db))
    print(f"[live] build 2026 eligible panel through {market_max}", flush=True)
    panel = fe.prepare_ml_data(
        start_date="20260101",
        end_date=market_max,
        target_horizon=cfg.horizon,
        min_market_cap=cfg.min_market_cap,
        use_cache=False,
        n_workers=1,
    )
    if panel.empty:
        raise RuntimeError("empty 2026 feature panel")
    panel = rpt.add_q5_proxy_fields(panel, db)
    panel = rpt.common_universe(panel).sort_values(["date", "stock_code"]).reset_index(drop=True)
    if panel.empty:
        raise RuntimeError("empty 2026 common eligible universe")

    panel_dates = sorted(panel["date"].astype(str).unique())
    latest_panel_date = panel_dates[-1]
    if latest_signal not in panel_dates:
        raise RuntimeError(f"latest scheduled 84-day signal {latest_signal} missing from eligible panel")

    day = panel[panel["date"].eq(latest_signal)].copy()
    day["market_cap"] = pd.to_numeric(day["market_cap"], errors="coerce")
    day = day[np.isfinite(day["market_cap"]) & (day["market_cap"] > 0)]
    by_market = day.groupby("market_type")["market_cap"].sum()
    kospi_cap = float(by_market.get("kospi", 0.0))
    kosdaq_cap = float(by_market.get("kosdaq", 0.0))
    total_cap = kospi_cap + kosdaq_cap
    if total_cap <= 0:
        raise RuntimeError("latest signal has no KOSPI/KOSDAQ market cap")

    equity_split = {
        "226490": kospi_cap / total_cap,
        "229200": kosdaq_cap / total_cap,
    }
    weights = {
        "226490": EQUITY_EXPOSURE * equity_split["226490"],
        "229200": EQUITY_EXPOSURE * equity_split["229200"],
        "214980": SAFE_EXPOSURE,
    }
    if abs(weights["226490"] + weights["229200"] - EQUITY_EXPOSURE) > 1e-12:
        raise RuntimeError(f"equity sleeve drift: {weights}")
    if abs(sum(weights.values()) - 1.0) > 1e-12:
        raise RuntimeError(f"full portfolio weight drift: {weights}")

    price_date, prices = fetch_etf_closes(market_max)
    order_rows = []
    for capital in capitals:
        order_rows.extend(target_holdings(capital, weights, prices, cfg.buy_cost))
    orders = pd.DataFrame(order_rows)
    orders.to_csv(out / "target_holdings.csv", index=False, encoding="utf-8-sig")

    snapshot_cols = [
        c for c in [
            "date", "stock_code", "name", "sector", "market_type", "market_cap",
            "closing_price", "avg_value_20d", "equity"
        ] if c in day.columns
    ]
    day[snapshot_cols].to_csv(
        out / "eligible_universe_latest_signal.csv", index=False, encoding="utf-8-sig"
    )

    market_fresh = market_stale_days <= MAX_MARKET_STALENESS_DAYS
    financial_fresh = financial_stale_days <= MAX_FINANCIAL_STALENESS_DAYS
    panel_reaches_market = latest_panel_date == market_max
    data_ready = bool(market_fresh and financial_fresh and panel_reaches_market)

    blocking_reason = None if data_ready else [
        reason for cond, reason in [
            (market_fresh, f"market data older than {MAX_MARKET_STALENESS_DAYS} calendar days"),
            (financial_fresh, f"PIT financial data older than {MAX_FINANCIAL_STALENESS_DAYS} days vs market data"),
            (panel_reaches_market, "eligible feature panel does not reach DB market max date"),
        ] if not cond
    ]

    status = {
        "strategy_id": "PQ-CORE-60-40-214980-V1",
        "strategy": "60% KODEX KOSPI/KOSDAQ150 dynamic eligible-market-cap split + 40% KODEX 단기채권PLUS",
        "equity_exposure": EQUITY_EXPOSURE,
        "defensive_exposure": SAFE_EXPOSURE,
        "defensive_code": ETF_CODES["safe"],
        "schedule_origin": SCHEDULE_ORIGIN,
        "horizon_trading_days": HORIZON,
        "historical_schedule_guard_last_signal": historical_schedule[-1],
        "db_market_max_date": market_max,
        "latest_panel_date": latest_panel_date,
        "latest_financial_available_date": fin_max,
        "market_staleness_calendar_days": market_stale_days,
        "financial_staleness_vs_market_days": financial_stale_days,
        "latest_scheduled_signal": latest_signal,
        "scheduled_signals_2026": [d for d in scheduled_all if d.startswith("2026")],
        "signal_execution_date": execution_date,
        "etf_price_date": price_date,
        "eligible_names": int(day["stock_code"].nunique()),
        "kospi_eligible_market_cap": kospi_cap,
        "kosdaq_eligible_market_cap": kosdaq_cap,
        "equity_child_split": equity_split,
        "target_weights": weights,
        "etf_prices": prices,
        "market_fresh": market_fresh,
        "financial_fresh": financial_fresh,
        "panel_reaches_market_max": panel_reaches_market,
        "DATA_READY": data_ready,
        "LIVE_READY": data_ready,
        "blocking_reason": blocking_reason,
        "note": "Indicative target holdings only. No brokerage order is submitted by this module.",
        "research_feature_config": asdict(cfg),
    }
    (out / "live_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)
    print("\n=== Indicative target holdings ===", flush=True)
    print(orders.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
