#!/usr/bin/env python3
"""Pre-registered personal-quant translation of the fractional cap benchmark.

This phase does NOT optimize alpha. It separates two questions that matter for
an individual Korean quant:

1. Historical Top-N tracking fidelity: can a concentrated cap-weighted basket
   preserve the full eligible-universe fractional cap benchmark?
2. Whole-share feasibility: at realistic capital levels, can those Top-N target
   weights actually be allocated using raw T+1 traded prices without excessive
   residual cash or missing positions?

The split is intentional. Backward-adjusted prices are correct for return
continuity but invalid for historical whole-share lot-size tests around splits.
Historical performance is therefore measured fractionally; lot feasibility is
measured independently at every rebalance with raw daily_prices.closing_price.

Frozen matrix (PR #1 comments 5364180007 and 5364210629, before results):
  capital: KRW 10m / 30m / 100m
  breadth: Top 20 / 50 / 100 by signal-date market cap
  weights: cap-weighted within selected Top-N
  rebalance: 42 trading days
  execution: T+1
  costs: buy 0.35%, sell 0.55%
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

import run_portable_tournament as rpt
from run_long_reversal_challenger import _register_corrected_mom36, _simulate_fractional_cap


CAPITALS = [10_000_000.0, 30_000_000.0, 100_000_000.0]
TOP_NS = [20, 50, 100]

FIDELITY_GATES = {
    "tracking_error_max": 0.05,
    "abs_cagr_gap_max": 0.015,
    "abs_sharpe_gap_max": 0.10,
    "abs_mdd_gap_max": 0.05,
    "avg_cash_ratio_max": 0.05,
    "max_cash_ratio_max": 0.15,
    "avg_position_fill_min": 0.90,
}

AUTHORITATIVE_REF = {
    "cagr": 0.10695381187087083,
    "sharpe": 0.5993211548642566,
    "max_drawdown": -0.40968564709184707,
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--alphakrx-root", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--feature-start", required=True)
    p.add_argument("--test-start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--output", default="outputs/personal_quant")
    return p.parse_args()


def topn_day(panel: pd.DataFrame, date: str, top_n: int | None):
    day = panel[panel["date"].eq(date)].dropna(subset=["market_cap"]).copy()
    day["market_cap"] = pd.to_numeric(day["market_cap"], errors="coerce")
    day = day[np.isfinite(day["market_cap"]) & (day["market_cap"] > 0)]
    day = day.sort_values(["market_cap", "stock_code"], ascending=[False, True])
    if top_n is not None:
        day = day.head(top_n)
    return day


def cap_events(panel: pd.DataFrame, rebal_dates: list[str], top_n: int | None):
    events = []
    for d in rebal_dates:
        day = topn_day(panel, d, top_n)
        if day.empty:
            continue
        w = day.set_index("stock_code")["market_cap"].astype(float)
        events.append((d, w / w.sum(), None))
    return events


def signal_frame(panel: pd.DataFrame, rebal_dates: list[str], top_n: int | None):
    parts = []
    for d in rebal_dates:
        day = topn_day(panel, d, top_n)[
            ["date", "stock_code", "name", "sector", "market_type", "market_cap"]
        ].copy()
        if day.empty:
            continue
        day["cap_rank"] = np.arange(1, len(day) + 1)
        day["target_weight"] = day["market_cap"] / day["market_cap"].sum()
        parts.append(day)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def save_fractional(root: Path, name: str, sig: pd.DataFrame, events, db: Path, cfg):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    sig.to_csv(d / "signals.csv", index=False, encoding="utf-8-sig")
    tx, ledger, eq = _simulate_fractional_cap(events, db, cfg)
    tx.to_csv(d / "transactions.csv", index=False, encoding="utf-8-sig")
    ledger.to_csv(d / "position_ledger.csv", index=False, encoding="utf-8-sig")
    eq.to_csv(d / "equity_curve.csv", index=False, encoding="utf-8-sig")
    sm = rpt.summarize(eq, tx, ledger, cfg)
    (d / "summary.json").write_text(json.dumps(sm, ensure_ascii=False, indent=2), encoding="utf-8")
    return sm, tx, eq


def tracking_error(eq: pd.DataFrame, ref_eq: pd.DataFrame):
    a = eq[["date", "equity"]].rename(columns={"equity": "candidate"})
    b = ref_eq[["date", "equity"]].rename(columns={"equity": "reference"})
    x = a.merge(b, on="date", how="inner").sort_values("date")
    x["cand_ret"] = pd.to_numeric(x["candidate"], errors="coerce").pct_change()
    x["ref_ret"] = pd.to_numeric(x["reference"], errors="coerce").pct_change()
    active = (x["cand_ret"] - x["ref_ret"]).dropna()
    return float(np.sqrt(252.0) * active.std(ddof=1)) if len(active) > 1 else np.nan


def historical_ops(eq: pd.DataFrame, tx: pd.DataFrame):
    e = eq.copy()
    if len(e) > 1 and int(e.iloc[-1].get("n_positions", 0)) == 0:
        e = e.iloc[:-1].copy()
    if e.empty:
        return {}
    dt = pd.to_datetime(e["date"], errors="coerce")
    years = max((dt.iloc[-1] - dt.iloc[0]).days / 365.25, 1 / 365.25)
    nonterminal = tx[~tx["side"].astype(str).eq("SELL_END")] if not tx.empty else tx
    avg_eq = float(pd.to_numeric(e["equity"], errors="coerce").mean())
    gross = float(nonterminal["gross_notional"].sum()) if not nonterminal.empty else 0.0
    return {
        "transactions_per_year": float(len(nonterminal) / years),
        "gross_turnover_per_year": float(gross / avg_eq / years) if avg_eq > 0 else np.nan,
    }


def subperiods(eq: pd.DataFrame):
    out = {}
    for label, start, end in [
        ("2018_2021", "20180101", "20211231"),
        ("2022_2024", "20220101", "20241231"),
        ("2025_2026", "20250101", "20261231"),
    ]:
        e = eq[(eq["date"] >= start) & (eq["date"] <= end)].copy()
        if len(e) < 2:
            out[label] = {"return": np.nan, "sharpe": np.nan, "mdd": np.nan}
            continue
        equity = pd.to_numeric(e["equity"], errors="coerce")
        r = equity.pct_change().fillna(0)
        sd = r.std(ddof=1)
        out[label] = {
            "return": float(equity.iloc[-1] / equity.iloc[0] - 1),
            "sharpe": float(np.sqrt(252) * r.mean() / sd) if sd and np.isfinite(sd) else np.nan,
            "mdd": float((equity / equity.cummax() - 1).min()),
        }
    return out


def trading_dates(db: Path, start: str, end: str):
    with sqlite3.connect(db) as con:
        x = pd.read_sql_query(
            "SELECT DISTINCT date FROM daily_prices WHERE date BETWEEN ? AND ? ORDER BY date",
            con,
            params=[start, end],
        )
    return x["date"].astype(str).tolist()


def raw_execution_prices(con: sqlite3.Connection, date: str, codes: list[str]):
    if not codes:
        return pd.DataFrame(columns=["stock_code", "closing_price", "value"])
    qs = ",".join("?" for _ in codes)
    return pd.read_sql_query(
        f"SELECT stock_code, closing_price, value FROM daily_prices WHERE date=? AND stock_code IN ({qs})",
        con,
        params=[date] + codes,
    )


def lot_feasibility(panel: pd.DataFrame, rebal_dates: list[str], top_n: int, capital: float, db: Path, cfg):
    dates = trading_dates(db, cfg.test_start, cfg.end)
    next_date = {}
    for d in rebal_dates:
        later = [x for x in dates if x > d]
        if later:
            next_date[d] = later[0]

    rows = []
    with sqlite3.connect(db) as con:
        for signal_date in rebal_dates:
            execution_date = next_date.get(signal_date)
            if execution_date is None:
                continue
            day = topn_day(panel, signal_date, top_n)
            if day.empty:
                continue
            weights = day.set_index("stock_code")["market_cap"].astype(float)
            weights = weights / weights.sum()
            codes = weights.index.tolist()
            px = raw_execution_prices(con, execution_date, codes).set_index("stock_code")

            # Reserve buy cost before sizing. This prevents an order sequence
            # artifact from deciding which final name loses its share.
            gross_budget = float(capital) / (1.0 + cfg.buy_cost)
            invested_gross = 0.0
            achieved = 0
            missing_or_untradable = 0
            for code, w in weights.items():
                if code not in px.index:
                    missing_or_untradable += 1
                    continue
                raw = float(pd.to_numeric(px.at[code, "closing_price"], errors="coerce"))
                value = float(pd.to_numeric(px.at[code, "value"], errors="coerce"))
                if not np.isfinite(raw) or raw <= 0 or not np.isfinite(value) or value <= 0:
                    missing_or_untradable += 1
                    continue
                shares = int(np.floor(gross_budget * float(w) / raw))
                if shares <= 0:
                    continue
                achieved += 1
                invested_gross += shares * raw

            buy_cost = invested_gross * cfg.buy_cost
            cash = float(capital) - invested_gross - buy_cost
            rows.append({
                "signal_date": signal_date,
                "execution_date": execution_date,
                "capital_krw": capital,
                "top_n": top_n,
                "target_positions": int(len(weights)),
                "achieved_positions": achieved,
                "missing_or_untradable": missing_or_untradable,
                "invested_gross": invested_gross,
                "buy_cost": buy_cost,
                "residual_cash": cash,
                "cash_ratio": cash / capital,
                "position_fill": achieved / len(weights) if len(weights) else np.nan,
                "max_target_weight": float(weights.max()) if len(weights) else np.nan,
            })

    snap = pd.DataFrame(rows)
    if snap.empty:
        return snap, {}
    metrics = {
        "avg_cash_ratio": float(snap["cash_ratio"].mean()),
        "max_cash_ratio": float(snap["cash_ratio"].max()),
        "avg_positions": float(snap["achieved_positions"].mean()),
        "min_positions": int(snap["achieved_positions"].min()),
        "avg_position_fill": float(snap["position_fill"].mean()),
        "min_position_fill": float(snap["position_fill"].min()),
        "max_target_weight": float(snap["max_target_weight"].max()),
        "missing_or_untradable_total": int(snap["missing_or_untradable"].sum()),
    }
    return snap, metrics


def validate_reference(sm: dict):
    diffs = {k: float(sm[k] - v) for k, v in AUTHORITATIVE_REF.items()}
    ok = all(abs(v) <= 1e-6 for v in diffs.values())
    if not ok:
        raise RuntimeError(f"fractional reference drifted from authoritative result: {diffs}")
    return diffs


def main():
    a = parse_args()
    alphakrx = Path(a.alphakrx_root).resolve()
    db = Path(a.db).resolve()
    out = Path(a.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(alphakrx))

    cfg = rpt.Config(a.feature_start, a.test_start, a.end)
    feature_engineer = _register_corrected_mom36(alphakrx, db, cfg)
    print("[panel] build common eligible panel", flush=True)
    fe = feature_engineer(str(db))
    panel = fe.prepare_ml_data(
        start_date=cfg.feature_start,
        end_date=cfg.end,
        target_horizon=cfg.horizon,
        min_market_cap=cfg.min_market_cap,
        use_cache=False,
        n_workers=1,
    )
    if panel.empty:
        raise RuntimeError("empty feature panel")
    panel = rpt.add_q5_proxy_fields(panel, db)
    panel = rpt.common_universe(panel).sort_values(["date", "stock_code"]).reset_index(drop=True)
    rebal = rpt.global_rebalance_dates(panel, cfg)
    if len(rebal) < 4:
        raise RuntimeError(f"too few rebalance dates: {len(rebal)}")
    print(f"[panel] rows={len(panel):,} names={panel.stock_code.nunique():,} rebalances={len(rebal)}", flush=True)

    sim_cfg = replace(cfg, initial_capital=100_000_000.0)
    ref_sig = signal_frame(panel, rebal, None)
    ref_sm, ref_tx, ref_eq = save_fractional(
        out, "fractional_full_cap_reference", ref_sig, cap_events(panel, rebal, None), db, sim_cfg
    )
    ref_diffs = validate_reference(ref_sm)
    print(f"[reference] validated against authoritative cap: {ref_diffs}", flush=True)

    perf = {}
    subs = {"fractional_full_cap_reference": subperiods(ref_eq)}
    for top_n in TOP_NS:
        name = f"cap_top{top_n}_fractional"
        sig = signal_frame(panel, rebal, top_n)
        sm, tx, eq = save_fractional(out, name, sig, cap_events(panel, rebal, top_n), db, sim_cfg)
        te = tracking_error(eq, ref_eq)
        hist = historical_ops(eq, tx)
        row = {
            **sm,
            "tracking_error": te,
            "cagr_gap_vs_fractional": float(sm["cagr"] - ref_sm["cagr"]),
            "sharpe_gap_vs_fractional": float(sm["sharpe"] - ref_sm["sharpe"]),
            "mdd_gap_vs_fractional": float(sm["max_drawdown"] - ref_sm["max_drawdown"]),
            **hist,
        }
        row["gate_tracking_error"] = bool(np.isfinite(te) and te <= FIDELITY_GATES["tracking_error_max"])
        row["gate_cagr_gap"] = bool(abs(row["cagr_gap_vs_fractional"]) <= FIDELITY_GATES["abs_cagr_gap_max"])
        row["gate_sharpe_gap"] = bool(abs(row["sharpe_gap_vs_fractional"]) <= FIDELITY_GATES["abs_sharpe_gap_max"])
        row["gate_mdd_gap"] = bool(abs(row["mdd_gap_vs_fractional"]) <= FIDELITY_GATES["abs_mdd_gap_max"])
        row["historical_tracking_pass"] = bool(
            row["gate_tracking_error"] and row["gate_cagr_gap"] and row["gate_sharpe_gap"] and row["gate_mdd_gap"]
        )
        perf[top_n] = row
        subs[name] = subperiods(eq)
        print(
            f"[{name}] Sharpe={sm['sharpe']:.3f} CAGR={sm['cagr']:.3%} "
            f"TE={te:.3%} historical_pass={row['historical_tracking_pass']}",
            flush=True,
        )

    rows = []
    lot_sub = {}
    for capital in CAPITALS:
        for top_n in TOP_NS:
            snap, lot = lot_feasibility(panel, rebal, top_n, capital, db, cfg)
            key = f"cap_top{top_n}_intlot_{int(capital / 1_000_000)}m"
            snap.to_csv(out / f"{key}_lot_snapshots.csv", index=False, encoding="utf-8-sig")
            lot_checks = {
                "avg_cash": bool(lot.get("avg_cash_ratio", np.inf) <= FIDELITY_GATES["avg_cash_ratio_max"]),
                "max_cash": bool(lot.get("max_cash_ratio", np.inf) <= FIDELITY_GATES["max_cash_ratio_max"]),
                "position_fill": bool(lot.get("avg_position_fill", -np.inf) >= FIDELITY_GATES["avg_position_fill_min"]),
            }
            p = perf[top_n]
            combined = bool(p["historical_tracking_pass"] and all(lot_checks.values()))
            rows.append({
                "strategy": key,
                "capital_krw": capital,
                "top_n": top_n,
                **{k: v for k, v in p.items() if k not in {"closed_positions", "end_equity", "win_rate_positions"}},
                **lot,
                **{f"gate_{k}": v for k, v in lot_checks.items()},
                "fidelity_pass": combined,
            })
            lot_sub[key] = lot
            print(
                f"[{key}] hist_pass={p['historical_tracking_pass']} "
                f"cash={lot.get('avg_cash_ratio', np.nan):.2%}/{lot.get('max_cash_ratio', np.nan):.2%} "
                f"fill={lot.get('avg_position_fill', np.nan):.1%} combined_pass={combined}",
                flush=True,
            )

    comp = pd.DataFrame(rows).sort_values(["capital_krw", "top_n"]).reset_index(drop=True)
    comp.to_csv(out / "comparison.csv", index=False, encoding="utf-8-sig")

    perf_table = pd.DataFrame([
        {"top_n": n, **perf[n]} for n in TOP_NS
    ]).sort_values("top_n")
    perf_table.to_csv(out / "topn_historical_tracking.csv", index=False, encoding="utf-8-sig")

    recommendations = {}
    for capital in CAPITALS:
        g = comp[comp["capital_krw"].eq(capital)].sort_values("top_n")
        passed = g[g["fidelity_pass"]]
        recommendations[str(int(capital))] = passed.iloc[0]["strategy"] if not passed.empty else None

    manifest = {
        "methodology_label": "pre-registered personal-quant benchmark translation; historical tracking separated from raw-price integer-lot feasibility",
        "preregistered_pr": 1,
        "preregistered_comment_ids": [5364180007, 5364210629],
        "config": asdict(cfg),
        "capital_grid_krw": CAPITALS,
        "top_n_grid": TOP_NS,
        "reference": "full eligible-universe fractional cap",
        "reference_validation_diffs": ref_diffs,
        "historical_tracking": "fractional Top-N vs fractional full cap, same T+1 and side-specific costs",
        "integer_lot_test": "independent rebalance snapshots sized with raw T+1 closing prices; buy cost reserved before floor-to-whole-share sizing",
        "fidelity_gates": FIDELITY_GATES,
        "selection_rule": "within each capital tier choose the smallest N that passes both historical tracking and raw-price lot gates; never select a capital tier by historical return",
        "recommendations_by_capital": recommendations,
        "subperiods": subs,
        "lot_metrics": lot_sub,
        "superseded_method": "historical integer simulation on backward-adjusted prices; rejected before results were inspected",
        "no_retuning_rule": "no active feature/rank/threshold/cost/holding-period change based on this translation matrix",
    }
    (out / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "recommendations.json").write_text(json.dumps(recommendations, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== Personal-quant investable cap translation ===", flush=True)
    print(comp.to_string(index=False), flush=True)
    print("recommendations_by_capital=", recommendations, flush=True)


if __name__ == "__main__":
    main()
