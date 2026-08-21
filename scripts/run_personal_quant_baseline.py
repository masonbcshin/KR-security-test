#!/usr/bin/env python3
"""Pre-registered personal-quant translation of the fractional cap benchmark.

This is not an alpha/factor search.  It asks whether the full-universe
fractional-share `universe_cap` research winner can be translated into a
whole-share portfolio that an individual Korean quant can actually execute.

Frozen matrix (registered in PR #1 before results were observed):
  capital: KRW 10m / 30m / 100m
  breadth: top 20 / 50 / 100 eligible stocks by signal-date market cap
  weights: cap-weighted within selected top-N
  execution: whole shares, T+1, 42 trading-day rebalance
  costs: buy 0.35%, sell 0.55%

Candidates are evaluated for fidelity to the authoritative full-universe
fractional-share cap benchmark, not for maximum historical return.
"""
from __future__ import annotations

import argparse
import json
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


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--alphakrx-root", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--feature-start", required=True)
    p.add_argument("--test-start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--output", default="outputs/personal_quant")
    return p.parse_args()


def topn_cap_events(panel: pd.DataFrame, rebal_dates: list[str], top_n: int):
    events = []
    for d in rebal_dates:
        day = panel[panel["date"].eq(d)].dropna(subset=["market_cap"]).copy()
        day["market_cap"] = pd.to_numeric(day["market_cap"], errors="coerce")
        day = day[np.isfinite(day["market_cap"]) & (day["market_cap"] > 0)]
        day = day.sort_values(["market_cap", "stock_code"], ascending=[False, True]).head(top_n)
        if day.empty:
            continue
        w = day.set_index("stock_code")["market_cap"].astype(float)
        events.append((d, w / w.sum(), None))
    return events


def signal_frame(panel: pd.DataFrame, rebal_dates: list[str], top_n: int | None = None):
    parts = []
    for d in rebal_dates:
        day = panel[panel["date"].eq(d)][
            ["date", "stock_code", "name", "sector", "market_type", "market_cap"]
        ].copy()
        day["market_cap"] = pd.to_numeric(day["market_cap"], errors="coerce")
        day = day.dropna(subset=["market_cap"]).sort_values(
            ["market_cap", "stock_code"], ascending=[False, True]
        )
        if top_n is not None:
            day = day.head(top_n)
        day["cap_rank"] = np.arange(1, len(day) + 1)
        denom = day["market_cap"].sum()
        day["target_weight"] = day["market_cap"] / denom if denom > 0 else np.nan
        parts.append(day)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def save_integer_candidate(root: Path, name: str, sig: pd.DataFrame, events, db: Path, cfg):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    sig.to_csv(d / "signals.csv", index=False, encoding="utf-8-sig")
    tx, ledger, eq = rpt.simulate_weights(events, db, cfg)
    tx.to_csv(d / "transactions.csv", index=False, encoding="utf-8-sig")
    ledger.to_csv(d / "position_ledger.csv", index=False, encoding="utf-8-sig")
    eq.to_csv(d / "equity_curve.csv", index=False, encoding="utf-8-sig")
    sm = rpt.summarize(eq, tx, ledger, cfg)
    (d / "summary.json").write_text(json.dumps(sm, ensure_ascii=False, indent=2), encoding="utf-8")
    return sm, tx, eq


def save_fractional_reference(root: Path, sig: pd.DataFrame, events, db: Path, cfg):
    d = root / "fractional_full_cap_reference"
    d.mkdir(parents=True, exist_ok=True)
    sig.to_csv(d / "signals.csv", index=False, encoding="utf-8-sig")
    tx, ledger, eq = _simulate_fractional_cap(events, db, cfg)
    tx.to_csv(d / "transactions.csv", index=False, encoding="utf-8-sig")
    ledger.to_csv(d / "position_ledger.csv", index=False, encoding="utf-8-sig")
    eq.to_csv(d / "equity_curve.csv", index=False, encoding="utf-8-sig")
    sm = rpt.summarize(eq, tx, ledger, cfg)
    (d / "summary.json").write_text(json.dumps(sm, ensure_ascii=False, indent=2), encoding="utf-8")
    return sm, tx, eq


def live_equity(eq: pd.DataFrame):
    e = eq.copy()
    if len(e) > 1 and int(e.iloc[-1].get("n_positions", 0)) == 0:
        e = e.iloc[:-1].copy()
    return e


def tracking_error(eq: pd.DataFrame, ref_eq: pd.DataFrame):
    a = eq[["date", "equity"]].rename(columns={"equity": "candidate"})
    b = ref_eq[["date", "equity"]].rename(columns={"equity": "reference"})
    x = a.merge(b, on="date", how="inner").sort_values("date")
    if len(x) < 3:
        return np.nan
    x["cand_ret"] = x["candidate"].pct_change()
    x["ref_ret"] = x["reference"].pct_change()
    active = (x["cand_ret"] - x["ref_ret"]).dropna()
    return float(np.sqrt(252.0) * active.std(ddof=1)) if len(active) > 1 else np.nan


def operational_metrics(eq: pd.DataFrame, tx: pd.DataFrame, target_n: int):
    e = live_equity(eq)
    if e.empty:
        return {}
    equity = pd.to_numeric(e["equity"], errors="coerce").replace(0, np.nan)
    cash = pd.to_numeric(e["cash"], errors="coerce")
    cash_ratio = cash / equity
    positions = pd.to_numeric(e["n_positions"], errors="coerce")
    dt = pd.to_datetime(e["date"], errors="coerce")
    years = max((dt.iloc[-1] - dt.iloc[0]).days / 365.25, 1 / 365.25)
    nonterminal_tx = tx[~tx["side"].astype(str).eq("SELL_END")] if not tx.empty else tx
    avg_equity = float(equity.mean())
    gross = float(nonterminal_tx["gross_notional"].sum()) if not nonterminal_tx.empty else 0.0
    return {
        "avg_cash_ratio": float(cash_ratio.mean()),
        "max_cash_ratio": float(cash_ratio.max()),
        "avg_positions": float(positions.mean()),
        "min_positions": int(positions.min()),
        "avg_position_fill": float(positions.mean() / target_n),
        "transactions_per_year": float(len(nonterminal_tx) / years),
        "gross_turnover_per_year": float(gross / avg_equity / years) if avg_equity > 0 else np.nan,
    }


def subperiods_from_eq(eq: pd.DataFrame):
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
        r = pd.to_numeric(e["equity"], errors="coerce").pct_change().fillna(0)
        total = float(e["equity"].iloc[-1] / e["equity"].iloc[0] - 1)
        sd = r.std(ddof=1)
        sharpe = float(np.sqrt(252) * r.mean() / sd) if sd and np.isfinite(sd) else np.nan
        mdd = float((e["equity"] / e["equity"].cummax() - 1).min())
        out[label] = {"return": total, "sharpe": sharpe, "mdd": mdd}
    return out


def main():
    a = parse_args()
    alphakrx = Path(a.alphakrx_root).resolve()
    db = Path(a.db).resolve()
    out = Path(a.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(alphakrx))

    base_cfg = rpt.Config(a.feature_start, a.test_start, a.end)
    feature_engineer = _register_corrected_mom36(alphakrx, db, base_cfg)
    print("[panel] build common eligible panel for personal-quant translation", flush=True)
    fe = feature_engineer(str(db))
    panel = fe.prepare_ml_data(
        start_date=base_cfg.feature_start,
        end_date=base_cfg.end,
        target_horizon=base_cfg.horizon,
        min_market_cap=base_cfg.min_market_cap,
        use_cache=False,
        n_workers=1,
    )
    if panel.empty:
        raise RuntimeError("empty feature panel")
    panel = rpt.add_q5_proxy_fields(panel, db)
    panel = rpt.common_universe(panel).sort_values(["date", "stock_code"]).reset_index(drop=True)
    rebal = rpt.global_rebalance_dates(panel, base_cfg)
    if len(rebal) < 4:
        raise RuntimeError(f"too few rebalance dates: {len(rebal)}")
    print(f"[panel] rows={len(panel):,} names={panel.stock_code.nunique():,} rebalances={len(rebal)}", flush=True)

    # Fractional full-universe reference. Return metrics are capital-scale invariant;
    # keep KRW 100m to match the authoritative research convention.
    ref_cfg = replace(base_cfg, initial_capital=100_000_000.0)
    ref_sig = signal_frame(panel, rebal, top_n=None)
    ref_sm, ref_tx, ref_eq = save_fractional_reference(
        out, ref_sig, rpt.cap_events(panel, rebal), db, ref_cfg
    )

    rows = []
    subs = {"fractional_full_cap_reference": subperiods_from_eq(ref_eq)}
    for capital in CAPITALS:
        cfg = replace(base_cfg, initial_capital=float(capital))
        for top_n in TOP_NS:
            name = f"cap_top{top_n}_int_{int(capital / 1_000_000)}m"
            sig = signal_frame(panel, rebal, top_n=top_n)
            events = topn_cap_events(panel, rebal, top_n)
            sm, tx, eq = save_integer_candidate(out, name, sig, events, db, cfg)
            op = operational_metrics(eq, tx, top_n)
            te = tracking_error(eq, ref_eq)
            cagr_gap = float(sm["cagr"] - ref_sm["cagr"])
            sharpe_gap = float(sm["sharpe"] - ref_sm["sharpe"])
            mdd_gap = float(sm["max_drawdown"] - ref_sm["max_drawdown"])
            checks = {
                "tracking_error": bool(np.isfinite(te) and te <= FIDELITY_GATES["tracking_error_max"]),
                "cagr_gap": bool(abs(cagr_gap) <= FIDELITY_GATES["abs_cagr_gap_max"]),
                "sharpe_gap": bool(abs(sharpe_gap) <= FIDELITY_GATES["abs_sharpe_gap_max"]),
                "mdd_gap": bool(abs(mdd_gap) <= FIDELITY_GATES["abs_mdd_gap_max"]),
                "avg_cash": bool(op.get("avg_cash_ratio", np.inf) <= FIDELITY_GATES["avg_cash_ratio_max"]),
                "max_cash": bool(op.get("max_cash_ratio", np.inf) <= FIDELITY_GATES["max_cash_ratio_max"]),
                "position_fill": bool(op.get("avg_position_fill", -np.inf) >= FIDELITY_GATES["avg_position_fill_min"]),
            }
            rows.append({
                "strategy": name,
                "capital_krw": capital,
                "top_n": top_n,
                **sm,
                "tracking_error": te,
                "cagr_gap_vs_fractional": cagr_gap,
                "sharpe_gap_vs_fractional": sharpe_gap,
                "mdd_gap_vs_fractional": mdd_gap,
                **op,
                **{f"gate_{k}": v for k, v in checks.items()},
                "fidelity_pass": bool(all(checks.values())),
            })
            subs[name] = subperiods_from_eq(eq)
            print(
                f"[{name}] Sharpe={sm['sharpe']:.3f} CAGR={sm['cagr']:.3%} "
                f"TE={te:.3%} cash={op.get('avg_cash_ratio', np.nan):.2%} pass={all(checks.values())}",
                flush=True,
            )

    comp = pd.DataFrame(rows).sort_values(["capital_krw", "top_n"]).reset_index(drop=True)
    comp.to_csv(out / "comparison.csv", index=False, encoding="utf-8-sig")

    recommendations = {}
    for capital in CAPITALS:
        g = comp[comp["capital_krw"].eq(capital)].sort_values("top_n")
        passed = g[g["fidelity_pass"]]
        recommendations[str(int(capital))] = (
            passed.iloc[0]["strategy"] if not passed.empty else None
        )

    manifest = {
        "methodology_label": "pre-registered investable benchmark translation; not alpha optimization",
        "preregistered_pr": 1,
        "preregistered_comment_id": 5364180007,
        "config": asdict(base_cfg),
        "capital_grid_krw": CAPITALS,
        "top_n_grid": TOP_NS,
        "weighting": "signal-date market-cap weight within top-N, renormalized",
        "share_policy": "integer whole shares for candidates; fractional shares only for authoritative reference",
        "reference": "full eligible universe fractional cap",
        "fidelity_gates": FIDELITY_GATES,
        "selection_rule": "within each capital tier choose the smallest N that passes every fidelity gate; do not select capital tier by historical return",
        "recommendations_by_capital": recommendations,
        "subperiods": subs,
        "no_retuning_rule": "no active feature/rank/threshold/cost/holding-period change based on this matrix",
    }
    (out / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "recommendations.json").write_text(
        json.dumps(recommendations, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n=== Personal-quant investable cap translation ===", flush=True)
    print(comp.to_string(index=False), flush=True)
    print("recommendations_by_capital=", recommendations, flush=True)


if __name__ == "__main__":
    main()
