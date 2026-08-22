#!/usr/bin/env python3
"""Pre-registered standalone 60-trading-day low-beta challenger.

Research ID: RL-2026-08-22-LOWBETA60-SINGLE-001
Pre-registration: PR #1 comment 5376895259, before standalone low-beta performance was inspected.

The only new signal is the existing audited AlphaKRX rolling_beta_60d, lower-is-better.
Universe, rebalance cadence, portfolio buffer, equal weighting, integer-share
execution, T+1 timing and costs are inherited unchanged from the audited static
active-strategy simulator.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import run_portable_tournament as rpt
from run_long_reversal_challenger import _register_corrected_mom36

RESEARCH_ID = "RL-2026-08-22-LOWBETA60-SINGLE-001"
PREREG_COMMENT_ID = 5376895259
BETA_COLUMN = "rolling_beta_60d"
BOOTSTRAP_PATHS = 20_000
BOOTSTRAP_BLOCK = 21
BOOTSTRAP_SEED = 20260822

BASELINE = {
    "cagr": 0.1210655172058861,
    "sharpe": 0.671471279920032,
    "max_drawdown": -0.43354248282924257,
    "calmar": 0.27924718338057225,
    "pre2025_sharpe": 0.14300697132632142,
    "subperiod_sharpe": {
        "2018_2021": 0.40174330973441336,
        "2022_2024": -0.23080420875632968,
        "2025_2026": 2.6970248773559153,
    },
}

GATES = {
    "full_sharpe_improvement_min": 0.10,
    "pre2025_sharpe_improvement_min": 0.10,
    "mdd_improvement_min": 0.05,
    "cagr_gap_min": -0.02,
    "bad_subperiod_sharpe_gap": -0.15,
    "max_bad_subperiods": 1,
    "max_transaction_cost_pct_initial": 0.10,
    "bootstrap_p_sharpe_better_min": 0.60,
}

DATA_GATES = {
    "min_beta_coverage": 0.70,
    "min_valid_beta_names": 200,
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--alphakrx-root", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--accepted-artifact-dir", required=True)
    p.add_argument("--feature-start", default="20150101")
    p.add_argument("--test-start", default="20180101")
    p.add_argument("--end", default="20260320")
    p.add_argument("--output", default="outputs/lowbeta60_single")
    return p.parse_args()


def load_accepted_baseline(root: Path):
    d = root / "cadence_84d"
    summary_path = d / "summary.json"
    equity_path = d / "equity_curve.csv"
    if not summary_path.exists() or not equity_path.exists():
        raise RuntimeError(f"accepted 84d baseline artifact incomplete: {d}")
    sm = json.loads(summary_path.read_text(encoding="utf-8"))
    diffs = {
        "cagr": float(sm["cagr"] - BASELINE["cagr"]),
        "sharpe": float(sm["sharpe"] - BASELINE["sharpe"]),
        "max_drawdown": float(sm["max_drawdown"] - BASELINE["max_drawdown"]),
        "calmar": float(sm["calmar"] - BASELINE["calmar"]),
    }
    if any(abs(v) > 1e-10 for v in diffs.values()):
        raise RuntimeError(f"accepted ETF baseline artifact drift: {diffs}")
    eq = pd.read_csv(equity_path, dtype={"date": str})
    eq["date"] = eq["date"].astype(str).str.zfill(8)
    return sm, eq, diffs


def period_stats(eq: pd.DataFrame, start: str, end: str):
    e = eq[(eq["date"] >= start) & (eq["date"] <= end)].copy()
    if len(e) < 2:
        return {"return": math.nan, "cagr": math.nan, "sharpe": math.nan, "mdd": math.nan}
    equity = pd.to_numeric(e["equity"], errors="coerce")
    r = equity.pct_change().fillna(0.0)
    sd = float(r.std(ddof=1))
    dt0 = pd.to_datetime(e["date"].iloc[0], format="%Y%m%d")
    dt1 = pd.to_datetime(e["date"].iloc[-1], format="%Y%m%d")
    years = max((dt1 - dt0).days / 365.25, 1 / 365.25)
    total = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    return {
        "return": total,
        "cagr": float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0),
        "sharpe": float(np.sqrt(252.0) * r.mean() / sd) if sd > 0 and np.isfinite(sd) else math.nan,
        "mdd": float((equity / equity.cummax() - 1.0).min()),
    }


def validate_baseline_subperiods(base_eq: pd.DataFrame):
    pre = period_stats(base_eq, "20180101", "20241231")
    subs = {
        "2018_2021": period_stats(base_eq, "20180101", "20211231"),
        "2022_2024": period_stats(base_eq, "20220101", "20241231"),
        "2025_2026": period_stats(base_eq, "20250101", "20260320"),
    }
    guard = {
        "pre2025_sharpe_diff": float(pre["sharpe"] - BASELINE["pre2025_sharpe"]),
        **{
            f"{k}_sharpe_diff": float(v["sharpe"] - BASELINE["subperiod_sharpe"][k])
            for k, v in subs.items()
        },
    }
    if any(abs(v) > 1e-9 for v in guard.values()):
        raise RuntimeError(f"accepted ETF subperiod baseline drift: {guard}")
    return pre, subs, guard


def beta_coverage(panel: pd.DataFrame, rebal_dates: list[str]):
    rows = []
    for d in rebal_dates:
        day = panel[panel["date"].eq(d)].copy()
        beta = pd.to_numeric(day[BETA_COLUMN], errors="coerce")
        finite = np.isfinite(beta)
        total = int(len(day))
        valid = int(finite.sum())
        coverage = valid / total if total else 0.0
        rows.append({
            "date": d,
            "eligible_names": total,
            "valid_beta_names": valid,
            "beta_coverage": coverage,
            "coverage_pass": bool(
                total > 0
                and valid >= DATA_GATES["min_valid_beta_names"]
                and coverage >= DATA_GATES["min_beta_coverage"]
            ),
        })
    return pd.DataFrame(rows)


def build_lowbeta_signals(panel: pd.DataFrame, rebal_dates: list[str]):
    parts = []
    for d in rebal_dates:
        day = panel[panel["date"].eq(d)].copy()
        beta = pd.to_numeric(day[BETA_COLUMN], errors="coerce")
        raw = -beta  # lower beta is better; rerank_market ranks larger raw score higher
        r = rpt.rerank_market(day, raw)
        r["strategy"] = "lowbeta60_single"
        parts.append(r[["date", "stock_code", "name", "sector", "market_type", "market_cap", "score", "rank_pos"]])
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def gate_result(low_sm: dict, low_eq: pd.DataFrame, base_sm: dict, base_eq: pd.DataFrame):
    low_pre = period_stats(low_eq, "20180101", "20241231")
    base_pre = period_stats(base_eq, "20180101", "20241231")
    low_sub = {
        "2018_2021": period_stats(low_eq, "20180101", "20211231"),
        "2022_2024": period_stats(low_eq, "20220101", "20241231"),
        "2025_2026": period_stats(low_eq, "20250101", "20260320"),
    }
    base_sub = {
        "2018_2021": period_stats(base_eq, "20180101", "20211231"),
        "2022_2024": period_stats(base_eq, "20220101", "20241231"),
        "2025_2026": period_stats(base_eq, "20250101", "20260320"),
    }
    bad = sum(
        float(low_sub[k]["sharpe"] - base_sub[k]["sharpe"]) < GATES["bad_subperiod_sharpe_gap"]
        for k in low_sub
    )
    cost_pct = float(low_sm["transaction_cost_krw"] / 100_000_000.0)
    vals = {
        "full_sharpe_improvement": float(low_sm["sharpe"] - base_sm["sharpe"]),
        "pre2025_sharpe_improvement": float(low_pre["sharpe"] - base_pre["sharpe"]),
        "mdd_improvement": float(low_sm["max_drawdown"] - base_sm["max_drawdown"]),
        "calmar_gap": float(low_sm["calmar"] - base_sm["calmar"]),
        "cagr_gap": float(low_sm["cagr"] - base_sm["cagr"]),
        "bad_subperiod_count": int(bad),
        "transaction_cost_pct_initial": cost_pct,
    }
    checks = {
        "full_sharpe": vals["full_sharpe_improvement"] >= GATES["full_sharpe_improvement_min"],
        "pre2025_sharpe": vals["pre2025_sharpe_improvement"] >= GATES["pre2025_sharpe_improvement_min"],
        "mdd": vals["mdd_improvement"] >= GATES["mdd_improvement_min"],
        "calmar": vals["calmar_gap"] >= 0.0,
        "cagr": vals["cagr_gap"] >= GATES["cagr_gap_min"],
        "subperiod_stability": bad <= GATES["max_bad_subperiods"],
        "cost": cost_pct <= GATES["max_transaction_cost_pct_initial"],
    }
    return vals, checks, bool(all(checks.values())), low_pre, low_sub


def _metrics(r: np.ndarray):
    growth = np.cumprod(1.0 + r)
    cagr = float(growth[-1] ** (252.0 / len(r)) - 1.0)
    sd = float(np.std(r, ddof=1))
    sharpe = float(np.sqrt(252.0) * np.mean(r) / sd) if sd > 0 else math.nan
    peak = np.maximum.accumulate(growth)
    mdd = float(np.min(growth / peak - 1.0))
    return cagr, sharpe, mdd


def paired_bootstrap(low_eq: pd.DataFrame, base_eq: pd.DataFrame):
    x = low_eq[["date", "equity"]].rename(columns={"equity": "lowbeta"}).merge(
        base_eq[["date", "equity"]].rename(columns={"equity": "base"}), on="date", how="inner"
    ).sort_values("date")
    low = pd.to_numeric(x["lowbeta"], errors="coerce").pct_change().fillna(0.0).to_numpy(float)
    base = pd.to_numeric(x["base"], errors="coerce").pct_change().fillna(0.0).to_numpy(float)
    n = len(low)
    if n < BOOTSTRAP_BLOCK * 2:
        raise RuntimeError("too few aligned returns for bootstrap")
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    nblocks = int(math.ceil(n / BOOTSTRAP_BLOCK))
    max_start = n - BOOTSTRAP_BLOCK
    ls, bs, lc, bc, lm, bm = [], [], [], [], [], []
    for _ in range(BOOTSTRAP_PATHS):
        starts = rng.integers(0, max_start + 1, size=nblocks)
        idx = np.concatenate([np.arange(s, s + BOOTSTRAP_BLOCK) for s in starts])[:n]
        lmet, bmet = _metrics(low[idx]), _metrics(base[idx])
        lc.append(lmet[0]); ls.append(lmet[1]); lm.append(lmet[2])
        bc.append(bmet[0]); bs.append(bmet[1]); bm.append(bmet[2])
    ls, bs, lc, bc, lm, bm = map(np.asarray, (ls, bs, lc, bc, lm, bm))

    def q(a):
        return {
            "p05": float(np.quantile(a, 0.05)),
            "p25": float(np.quantile(a, 0.25)),
            "median": float(np.quantile(a, 0.50)),
            "p95": float(np.quantile(a, 0.95)),
        }

    return {
        "paths": BOOTSTRAP_PATHS,
        "block_days": BOOTSTRAP_BLOCK,
        "seed": BOOTSTRAP_SEED,
        "lowbeta_sharpe": q(ls),
        "baseline_sharpe": q(bs),
        "lowbeta_cagr": q(lc),
        "baseline_cagr": q(bc),
        "lowbeta_mdd": q(lm),
        "baseline_mdd": q(bm),
        "p_lowbeta_sharpe_gt_baseline": float(np.mean(ls > bs)),
        "p_lowbeta_cagr_gt_baseline": float(np.mean(lc > bc)),
        "median_sharpe_edge": float(np.median(ls - bs)),
        "median_cagr_edge": float(np.median(lc - bc)),
    }


def main():
    a = parse_args()
    alphakrx = Path(a.alphakrx_root).resolve()
    db = Path(a.db).resolve()
    artifact = Path(a.accepted_artifact_dir).resolve()
    out = Path(a.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(alphakrx))

    base_sm, base_eq, base_guard = load_accepted_baseline(artifact)
    base_pre, base_sub, base_sub_guard = validate_baseline_subperiods(base_eq)

    cfg = rpt.Config(a.feature_start, a.test_start, a.end)
    fe_cls = _register_corrected_mom36(alphakrx, db, cfg)
    print("[panel] build same audited PIT feature panel for low-beta", flush=True)
    fe = fe_cls(str(db))
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
    if BETA_COLUMN not in panel.columns:
        raise KeyError(f"{BETA_COLUMN} missing from audited feature panel")

    rebal = rpt.global_rebalance_dates(panel, cfg)
    coverage = beta_coverage(panel, rebal)
    coverage.to_csv(out / "beta_coverage.csv", index=False, encoding="utf-8-sig")
    data_quality_pass = bool(len(coverage) > 0 and coverage["coverage_pass"].all())

    result = {
        "research_id": RESEARCH_ID,
        "preregistered_comment_id": PREREG_COMMENT_ID,
        "methodology_label": "pre-registered retrospective/pseudo-OOS standalone low-beta challenger; not untouched forward OOS",
        "signal": {"column": BETA_COLUMN, "direction": "lower_is_better", "window_trading_days": 60},
        "data_quality_pass": data_quality_pass,
        "data_quality": {
            "n_rebalances": int(len(coverage)),
            "min_coverage": float(coverage["beta_coverage"].min()) if len(coverage) else None,
            "median_coverage": float(coverage["beta_coverage"].median()) if len(coverage) else None,
            "min_valid_names": int(coverage["valid_beta_names"].min()) if len(coverage) else None,
            "failed_dates": coverage.loc[~coverage["coverage_pass"], "date"].astype(str).tolist(),
            "gates": DATA_GATES,
        },
        "accepted_baseline": base_sm,
        "baseline_guard_diffs": base_guard,
        "baseline_subperiod_guard_diffs": base_sub_guard,
        "baseline_pre2025": base_pre,
        "baseline_subperiods": base_sub,
        "gates": GATES,
    }

    if not data_quality_pass:
        result.update({"decision": "DATA_QUALITY_FAIL", "primary_pass": False, "lowbeta": None, "bootstrap": None})
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return

    sig = build_lowbeta_signals(panel, rebal)
    sig.to_csv(out / "signals.csv", index=False, encoding="utf-8-sig")
    low_sm = rpt.save_result(out, "lowbeta60_single", sig, rpt.events_from_signals(sig, cfg), db, cfg)
    low_eq = pd.read_csv(out / "lowbeta60_single" / "equity_curve.csv", dtype={"date": str})
    low_eq["date"] = low_eq["date"].astype(str).str.zfill(8)
    tx = pd.read_csv(out / "lowbeta60_single" / "transactions.csv")

    vals, checks, primary_pass, low_pre, low_sub = gate_result(low_sm, low_eq, base_sm, base_eq)
    nonterminal = tx[~tx["side"].astype(str).eq("SELL_END")].copy() if not tx.empty else tx
    years = max((pd.to_datetime(cfg.end) - pd.to_datetime(cfg.test_start)).days / 365.25, 1.0)
    ops = {
        "nonterminal_transactions": int(len(nonterminal)),
        "transactions_per_year": float(len(nonterminal) / years),
        "gross_turnover_multiple": float(low_sm["gross_traded_krw"] / cfg.initial_capital),
        "transaction_cost_pct_initial_capital": float(low_sm["transaction_cost_krw"] / cfg.initial_capital),
    }

    result.update({
        "lowbeta": low_sm,
        "lowbeta_pre2025": low_pre,
        "lowbeta_subperiods": low_sub,
        "gate_values": vals,
        "gate_checks": checks,
        "primary_pass": primary_pass,
        "operations": ops,
    })

    if primary_pass:
        boot = paired_bootstrap(low_eq, base_eq)
        boot_pass = bool(boot["p_lowbeta_sharpe_gt_baseline"] >= GATES["bootstrap_p_sharpe_better_min"])
        result["bootstrap"] = boot
        result["bootstrap_pass"] = boot_pass
        result["decision"] = "ADVANCE_TO_PROSPECTIVE" if boot_pass else "REJECT_BOOTSTRAP"
    else:
        result["bootstrap"] = None
        result["bootstrap_pass"] = None
        result["decision"] = "REJECT_PRIMARY_NO_RESCUE_TUNING"

    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
