#!/usr/bin/env python3
"""Pre-registered ETF rebalance-cadence robustness test.

Frozen in PR #1 comment 5371279681 before 21/63/84-day results were observed.
This is a same-history sensitivity analysis, not independent OOS validation.

The authoritative fractional full-cap benchmark remains on its original
42-trading-day rebalance rule.  Only the accepted ETF proxy's own target-weight
refresh cadence changes: 21 / 42 / 63 / 84 trading days.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd
import FinanceDataReader as fdr

import run_portable_tournament as rpt
import run_personal_quant_baseline as pq
import run_etf_proxy_baseline as ep
from run_long_reversal_challenger import _register_corrected_mom36


CADENCES = [21, 42, 63, 84]
ETF_CANDIDATE = {"codes": ["226490", "229200"], "mode": "market_split"}
PREREG_COMMENT_ID = 5371279681
FDR_VERSION = "0.9.201"

FIDELITY_GATES = {
    "tracking_error_max": 0.05,
    "abs_cagr_gap_max": 0.015,
    "abs_sharpe_gap_max": 0.10,
    "abs_mdd_gap_max": 0.05,
}

# Guard against implementation drift: the 42-day row must reproduce the
# already accepted ETF proxy baseline before any cadence comparison is trusted.
KNOWN_42 = {
    "cagr": 0.12094300977020955,
    "sharpe": 0.671170089291581,
    "max_drawdown": -0.43237841558978996,
    "tracking_error": 0.03662900410318135,
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--alphakrx-root", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--feature-start", required=True)
    p.add_argument("--test-start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--output", default="outputs/etf_rebalance_robustness")
    return p.parse_args()


def cadence_dates(panel: pd.DataFrame, test_start: str, end: str, cadence: int) -> list[str]:
    dates = sorted(str(d) for d in panel["date"].unique() if test_start <= str(d) <= end)
    return dates[::cadence]


def fidelity_checks(sm: dict, te: float, ref_sm: dict):
    gaps = {
        "cagr_gap_vs_fractional": float(sm["cagr"] - ref_sm["cagr"]),
        "sharpe_gap_vs_fractional": float(sm["sharpe"] - ref_sm["sharpe"]),
        "mdd_gap_vs_fractional": float(sm["max_drawdown"] - ref_sm["max_drawdown"]),
    }
    checks = {
        "tracking_error": bool(np.isfinite(te) and te <= FIDELITY_GATES["tracking_error_max"]),
        "cagr_gap": bool(abs(gaps["cagr_gap_vs_fractional"]) <= FIDELITY_GATES["abs_cagr_gap_max"]),
        "sharpe_gap": bool(abs(gaps["sharpe_gap_vs_fractional"]) <= FIDELITY_GATES["abs_sharpe_gap_max"]),
        "mdd_gap": bool(abs(gaps["mdd_gap_vs_fractional"]) <= FIDELITY_GATES["abs_mdd_gap_max"]),
    }
    return gaps, checks, bool(all(checks.values()))


def validate_42(row: dict):
    diffs = {
        "cagr": float(row["cagr"] - KNOWN_42["cagr"]),
        "sharpe": float(row["sharpe"] - KNOWN_42["sharpe"]),
        "max_drawdown": float(row["max_drawdown"] - KNOWN_42["max_drawdown"]),
        "tracking_error": float(row["tracking_error"] - KNOWN_42["tracking_error"]),
    }
    if any(abs(v) > 1e-10 for v in diffs.values()):
        raise RuntimeError(f"42-day ETF baseline drifted from accepted result: {diffs}")
    return diffs


def choose_cadence(rows: pd.DataFrame, subs: dict):
    """Apply only the selection rule frozen in PR comment 5371279681."""
    base42 = subs["42"]
    stable_flags = {}
    for _, r in rows.iterrows():
        key = str(int(r["cadence_days"]))
        worse = 0
        for period in ["2018_2021", "2022_2024", "2025_2026"]:
            s = subs[key][period]["sharpe"]
            b = base42[period]["sharpe"]
            if np.isfinite(s) and np.isfinite(b) and s < b - 0.15:
                worse += 1
        stable_flags[key] = {"worse_than_42_by_gt_0p15_count": worse, "subperiod_stability_pass": worse < 2}

    x = rows.copy()
    x["subperiod_stability_pass"] = x["cadence_days"].map(lambda v: stable_flags[str(int(v))]["subperiod_stability_pass"])
    x["selection_eligible"] = x["fidelity_pass"] & x["subperiod_stability_pass"]

    eligible = x[x["selection_eligible"]].copy()
    if eligible.empty:
        x["performance_plateau"] = False
        return None, x, stable_flags, {}

    best_sharpe = float(eligible["sharpe"].max())
    best_calmar = float(eligible["calmar"].max())
    eligible["performance_plateau"] = (
        (eligible["sharpe"] >= best_sharpe - 0.03)
        & (eligible["calmar"] >= best_calmar * 0.90)
    )
    plateau_keys = set(eligible.loc[eligible["performance_plateau"], "cadence_days"].astype(int).tolist())
    x["performance_plateau"] = x["cadence_days"].astype(int).isin(plateau_keys)

    plateau = x[x["performance_plateau"]].copy()
    # Frozen operational tie-break: fewer transactions/year, then lower modeled cost.
    winner = plateau.sort_values(
        ["transactions_per_year", "transaction_cost_krw", "cadence_days"],
        ascending=[True, True, True],
    ).iloc[0]
    detail = {
        "best_eligible_sharpe": best_sharpe,
        "best_eligible_calmar": best_calmar,
        "plateau_sharpe_floor": best_sharpe - 0.03,
        "plateau_calmar_floor": best_calmar * 0.90,
        "plateau_cadences": sorted(plateau_keys),
    }
    return int(winner["cadence_days"]), x, stable_flags, detail


def main():
    a = parse_args()
    alphakrx = Path(a.alphakrx_root).resolve()
    db = Path(a.db).resolve()
    out = Path(a.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(alphakrx))

    installed_fdr = getattr(fdr, "__version__", None)
    if installed_fdr and installed_fdr != FDR_VERSION:
        raise RuntimeError(f"FinanceDataReader version drift: {installed_fdr} != {FDR_VERSION}")

    # Keep the research benchmark definition fixed at its authoritative 42-day horizon.
    cfg = rpt.Config(a.feature_start, a.test_start, a.end)
    if cfg.horizon != 42:
        raise RuntimeError(f"authoritative reference horizon drifted: {cfg.horizon}")

    frames, audit = ep.fetch_etf_prices(cfg.test_start, cfg.end, out)
    raw, volume = ep.common_price_frames(frames, cfg.test_start, cfg.end)

    feature_engineer = _register_corrected_mom36(alphakrx, db, cfg)
    print("[panel] build common eligible panel once for all cadence schedules", flush=True)
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

    # Authoritative full-cap reference stays exactly on the original 42-day schedule.
    ref_rebal = rpt.global_rebalance_dates(panel, cfg)
    sim_cfg = replace(cfg, initial_capital=100_000_000.0)
    ref_sig = pq.signal_frame(panel, ref_rebal, None)
    ref_sm, _, ref_eq = pq.save_fractional(
        out,
        "fractional_full_cap_reference",
        ref_sig,
        pq.cap_events(panel, ref_rebal, None),
        db,
        sim_cfg,
    )
    ref_diffs = pq.validate_reference(ref_sm)
    print(f"[reference] reproduced authoritative 42-day full-cap: {ref_diffs}", flush=True)

    rows = []
    subperiod_results = {}
    signal_ranges = {}
    guard42 = None

    for cadence in CADENCES:
        rebal = cadence_dates(panel, cfg.test_start, cfg.end, cadence)
        events, sig = ep.candidate_events(panel, rebal, ETF_CANDIDATE)
        d = out / f"cadence_{cadence}d"
        d.mkdir(parents=True, exist_ok=True)
        sig.to_csv(d / "signals.csv", index=False, encoding="utf-8-sig")

        tx, ledger, eq = ep.simulate_fractional_etf(events, raw, volume, sim_cfg)
        tx.to_csv(d / "transactions.csv", index=False, encoding="utf-8-sig")
        eq.to_csv(d / "equity_curve.csv", index=False, encoding="utf-8-sig")
        sm = rpt.summarize(eq, tx, ledger, sim_cfg)
        te = pq.tracking_error(eq, ref_eq)
        gaps, checks, fidelity_pass = fidelity_checks(sm, te, ref_sm)
        ops = pq.historical_ops(eq, tx)
        subs = pq.subperiods(eq)
        subperiod_results[str(cadence)] = subs
        signal_ranges[str(cadence)] = {
            "n_rebalances": len(rebal),
            "first_signal": rebal[0] if rebal else None,
            "last_signal": rebal[-1] if rebal else None,
        }
        row = {
            "cadence_days": cadence,
            "n_rebalances": len(rebal),
            **sm,
            "tracking_error": te,
            **gaps,
            **ops,
            **{f"gate_{k}": v for k, v in checks.items()},
            "fidelity_pass": fidelity_pass,
        }
        rows.append(row)
        (d / "summary.json").write_text(json.dumps({**sm, "tracking_error": te, "subperiods": subs}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"[{cadence}d] rebalances={len(rebal)} CAGR={sm['cagr']:.3%} "
            f"Sharpe={sm['sharpe']:.3f} Calmar={sm['calmar']:.3f} "
            f"MDD={sm['max_drawdown']:.3%} TE={te:.3%} "
            f"tx/y={ops.get('transactions_per_year', np.nan):.1f} pass={fidelity_pass}",
            flush=True,
        )

    results = pd.DataFrame(rows).sort_values("cadence_days").reset_index(drop=True)
    row42 = results.loc[results["cadence_days"].eq(42)].iloc[0].to_dict()
    guard42 = validate_42(row42)
    print(f"[guard] 42-day accepted ETF baseline reproduced: {guard42}", flush=True)

    selected, results, stability, plateau_detail = choose_cadence(results, subperiod_results)
    results.to_csv(out / "robustness_comparison.csv", index=False, encoding="utf-8-sig")

    sub_rows = []
    for cadence in CADENCES:
        for period, vals in subperiod_results[str(cadence)].items():
            sub_rows.append({"cadence_days": cadence, "period": period, **vals})
    pd.DataFrame(sub_rows).to_csv(out / "subperiod_comparison.csv", index=False, encoding="utf-8-sig")

    selection = {
        "selected_cadence_days": selected,
        "selection_status": "selected_from_preregistered_robustness_rule" if selected is not None else "no_cadence_passed_preregistered_rule",
        "stability_checks": stability,
        "plateau_detail": plateau_detail,
        "important_label": "same-history robustness/sensitivity analysis; NOT independent OOS validation",
    }
    (out / "selection.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = {
        "methodology_label": "pre-registered ETF rebalance-cadence robustness test",
        "preregistered_pr": 1,
        "preregistered_comment_id": PREREG_COMMENT_ID,
        "finance_datareader_version": FDR_VERSION,
        "candidate_etfs": ETF_CANDIDATE,
        "cadences_days": CADENCES,
        "authoritative_reference_cadence_days": 42,
        "config": asdict(cfg),
        "fidelity_gates": FIDELITY_GATES,
        "reference_validation_diffs": ref_diffs,
        "guard_42_diffs": guard42,
        "signal_ranges": signal_ranges,
        "subperiods": subperiod_results,
        "selection": selection,
        "anti_overfit_rule": "fidelity gates -> subperiod stability -> broad Sharpe/Calmar plateau -> lowest operational burden",
        "no_retuning_rule": "do not add cadences or alter thresholds after observing results",
    }
    (out / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== Rebalance cadence robustness ===", flush=True)
    print(results.to_string(index=False), flush=True)
    print("\n=== Selection ===", flush=True)
    print(json.dumps(selection, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
