#!/usr/bin/env python3
"""Preregistered 2-ETF 63-session inverse-volatility challenger.

Research ID: RL-2026-08-22-ETF-IVOL63-001
Preregistration: PR #1 comment 5380794609, before performance inspection.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import FinanceDataReader as fdr
import numpy as np
import pandas as pd

import run_etf_proxy_baseline as ep
import run_personal_quant_baseline as pq
import run_portable_tournament as rpt

RESEARCH_ID = "RL-2026-08-22-ETF-IVOL63-001"
PREREG_COMMENT_ID = 5380794609
CODES = ["226490", "229200"]
VOL_LOOKBACK = 63
FDR_VERSION = "0.9.201"
BOOTSTRAP_PATHS = 20_000
BOOTSTRAP_BLOCK = 21
BOOTSTRAP_SEED = 20260822

KNOWN_84 = {
    "cagr": 0.1210655172058861,
    "sharpe": 0.671471279920032,
    "max_drawdown": -0.43354248282924257,
    "calmar": 0.27924718338057225,
}

GATES = {
    "full_sharpe_improvement_min": 0.10,
    "pre2025_sharpe_improvement_min": 0.10,
    "mdd_improvement_min": 0.05,
    "cagr_gap_min": -0.01,
    "bad_subperiod_sharpe_gap": -0.15,
    "max_bad_subperiods": 1,
    "max_transaction_cost_pct_initial": 0.05,
    "bootstrap_p_sharpe_better_min": 0.60,
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--accepted-artifact-dir", required=True)
    p.add_argument("--test-start", default="20180101")
    p.add_argument("--end", default="20260320")
    p.add_argument("--output", default="outputs/etf_ivol63")
    return p.parse_args()


def load_base_events(root: Path):
    d = root / "cadence_84d"
    sig_path = d / "signals.csv"
    summary_path = d / "summary.json"
    equity_path = d / "equity_curve.csv"
    if not sig_path.exists() or not summary_path.exists() or not equity_path.exists():
        raise RuntimeError(f"accepted 84d artifact incomplete: {d}")

    sig = pd.read_csv(sig_path, dtype={"date": str, "stock_code": str})
    sig["date"] = sig["date"].astype(str).str.zfill(8)
    sig["stock_code"] = sig["stock_code"].astype(str).str.zfill(6)
    sig["target_weight"] = pd.to_numeric(sig["target_weight"], errors="raise")
    if set(sig["stock_code"].unique()) != set(CODES):
        raise RuntimeError(f"unexpected accepted ETF codes: {sorted(sig['stock_code'].unique())}")

    events = []
    for date, day in sig.groupby("date", sort=True):
        weights = day.set_index("stock_code")["target_weight"].astype(float).reindex(CODES).fillna(0.0)
        if abs(float(weights.sum()) - 1.0) > 1e-10:
            raise RuntimeError(f"accepted weights do not sum to one on {date}: {weights.to_dict()}")
        events.append((str(date), weights, None))

    stored_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    stored_eq = pd.read_csv(equity_path, dtype={"date": str})
    stored_eq["date"] = stored_eq["date"].astype(str).str.zfill(8)
    return events, sig, stored_summary, stored_eq


def fetch_prices(test_start: str, end: str, out: Path):
    start = (pd.Timestamp(test_start) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    end_iso = pd.Timestamp(end).strftime("%Y-%m-%d")
    frames = {}
    audits = []

    for code in CODES:
        df = fdr.DataReader(f"NAVER:{code}", start, end_iso).copy()
        if df.empty:
            raise RuntimeError(f"ETF data empty: {code}")
        df = df.reset_index()
        if "Date" not in df.columns:
            df = df.rename(columns={df.columns[0]: "Date"})
        df["date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y%m%d")
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["date", "Close"]).sort_values("date").drop_duplicates("date")
        df = df[["date", "Open", "High", "Low", "Close", "Volume"]].reset_index(drop=True)

        move = df["Close"].pct_change().abs()
        audit = {
            "stock_code": code,
            "rows": int(len(df)),
            "date_min": str(df["date"].min()),
            "date_max": str(df["date"].max()),
            "max_abs_daily_move": float(move.max(skipna=True)),
            "rows_abs_move_gt_30pct": int((move > 0.30 + 1e-12).sum()),
            "zero_or_bad_close_rows": int((~np.isfinite(df["Close"]) | (df["Close"] <= 0)).sum()),
        }
        audits.append(audit)
        df.to_csv(out / f"etf_extended_{code}.csv", index=False, encoding="utf-8-sig")
        frames[code] = df

    audit_df = pd.DataFrame(audits)
    audit_df.to_csv(out / "etf_data_audit.csv", index=False, encoding="utf-8-sig")
    if (audit_df["rows_abs_move_gt_30pct"] > 0).any() or (audit_df["zero_or_bad_close_rows"] > 0).any():
        raise RuntimeError(f"ETF price integrity failure: {audit_df.to_dict('records')}")
    return frames


def price_frames(frames: dict[str, pd.DataFrame], test_start: str, end: str):
    ext_close = raw = volume = None
    for code, df in frames.items():
        x = df.set_index("date")
        e = x[["Close"]].rename(columns={"Close": code})
        ext_close = e if ext_close is None else ext_close.join(e, how="outer")
        y = x[(x.index >= test_start) & (x.index <= end)]
        c = y[["Close"]].rename(columns={"Close": code})
        v = y[["Volume"]].rename(columns={"Volume": code})
        raw = c if raw is None else raw.join(c, how="outer")
        volume = v if volume is None else volume.join(v, how="outer")
    if ext_close is None or raw is None or volume is None:
        raise RuntimeError("failed to build ETF price frames")
    return ext_close.sort_index(), raw.sort_index(), volume.reindex(raw.index).sort_index()


def build_ivol_events(ext_close: pd.DataFrame, test_start: str, end: str):
    common = ext_close[CODES].dropna(how="any").copy()
    if len(common) < VOL_LOOKBACK + 2:
        raise RuntimeError("insufficient common ETF history")

    returns = common.pct_change()
    rolling_vol = returns.rolling(VOL_LOOKBACK, min_periods=VOL_LOOKBACK).std(ddof=1)
    table = rolling_vol.copy()
    table["_dt"] = pd.to_datetime(table.index, format="%Y%m%d", errors="coerce")
    table = table.dropna(subset=["_dt"])
    table["_month"] = table["_dt"].dt.to_period("M")
    month_end = table.groupby("_month", sort=True).tail(1).sort_values("_dt")

    eligible = []
    for idx, row in month_end.iterrows():
        vals = pd.to_numeric(row[CODES], errors="coerce")
        if vals.isna().any() or not np.isfinite(vals.to_numpy(float)).all() or (vals <= 0).any():
            continue
        eligible.append(str(idx))

    pre = [d for d in eligible if d < test_start]
    keep = ([max(pre)] if pre else []) + [d for d in eligible if test_start <= d <= end]
    keep = sorted(set(keep))
    if not keep or keep[0] >= test_start:
        raise RuntimeError("no eligible pre-test month-end volatility state")

    events = []
    rows = []
    for d in keep:
        sigma = rolling_vol.loc[d, CODES].astype(float)
        inv = 1.0 / sigma
        weights = inv / inv.sum()
        if abs(float(weights.sum()) - 1.0) > 1e-12 or (weights <= 0).any():
            raise RuntimeError(f"invalid IVOL weights on {d}: {weights.to_dict()}")
        events.append((d, weights, None))
        for code in CODES:
            rows.append({
                "date": d,
                "stock_code": code,
                "vol_63d": float(sigma[code]),
                "inverse_vol": float(inv[code]),
                "target_weight": float(weights[code]),
            })

    signal_df = pd.DataFrame(rows)
    return events, signal_df, rolling_vol


def validate_baseline(summary: dict):
    diffs = {key: float(summary[key] - expected) for key, expected in KNOWN_84.items()}
    if any(abs(value) > 1e-10 for value in diffs.values()):
        raise RuntimeError(f"accepted ETF baseline drift: {diffs}")
    return diffs


def period_stats(eq: pd.DataFrame, start: str, end: str):
    frame = eq[(eq["date"] >= start) & (eq["date"] <= end)].copy()
    if len(frame) < 2:
        return {"return": math.nan, "cagr": math.nan, "sharpe": math.nan, "mdd": math.nan}
    equity = pd.to_numeric(frame["equity"], errors="coerce")
    daily = equity.pct_change().fillna(0.0)
    sd = float(daily.std(ddof=1))
    dt0 = pd.to_datetime(frame["date"].iloc[0], format="%Y%m%d")
    dt1 = pd.to_datetime(frame["date"].iloc[-1], format="%Y%m%d")
    years = max((dt1 - dt0).days / 365.25, 1 / 365.25)
    total = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    return {
        "return": total,
        "cagr": float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0),
        "sharpe": float(np.sqrt(252.0) * daily.mean() / sd) if sd > 0 and np.isfinite(sd) else math.nan,
        "mdd": float((equity / equity.cummax() - 1.0).min()),
    }


def evaluate_gates(ch, base, ch_eq, base_eq, cfg):
    ch_pre = period_stats(ch_eq, "20180101", "20241231")
    base_pre = period_stats(base_eq, "20180101", "20241231")
    ch_sub = pq.subperiods(ch_eq)
    base_sub = pq.subperiods(base_eq)

    bad = 0
    for period in ("2018_2021", "2022_2024", "2025_2026"):
        gap = float(ch_sub[period]["sharpe"] - base_sub[period]["sharpe"])
        if gap < GATES["bad_subperiod_sharpe_gap"]:
            bad += 1

    cost_pct = float(ch["transaction_cost_krw"] / cfg.initial_capital)
    values = {
        "full_sharpe_improvement": float(ch["sharpe"] - base["sharpe"]),
        "pre2025_sharpe_improvement": float(ch_pre["sharpe"] - base_pre["sharpe"]),
        "mdd_improvement": float(ch["max_drawdown"] - base["max_drawdown"]),
        "calmar_gap": float(ch["calmar"] - base["calmar"]),
        "cagr_gap": float(ch["cagr"] - base["cagr"]),
        "bad_subperiod_count": int(bad),
        "transaction_cost_pct_initial": cost_pct,
    }
    checks = {
        "full_sharpe": values["full_sharpe_improvement"] >= GATES["full_sharpe_improvement_min"],
        "pre2025_sharpe": values["pre2025_sharpe_improvement"] >= GATES["pre2025_sharpe_improvement_min"],
        "mdd": values["mdd_improvement"] >= GATES["mdd_improvement_min"],
        "calmar": values["calmar_gap"] >= 0.0,
        "cagr": values["cagr_gap"] >= GATES["cagr_gap_min"],
        "subperiod_stability": bad <= GATES["max_bad_subperiods"],
        "cost": cost_pct <= GATES["max_transaction_cost_pct_initial"],
    }
    return values, checks, bool(all(checks.values())), ch_pre, base_pre, ch_sub, base_sub


def _metrics(returns: np.ndarray):
    growth = np.cumprod(1.0 + returns)
    cagr = float(growth[-1] ** (252.0 / len(returns)) - 1.0)
    sd = float(np.std(returns, ddof=1))
    sharpe = float(np.sqrt(252.0) * np.mean(returns) / sd) if sd > 0 else math.nan
    peak = np.maximum.accumulate(growth)
    mdd = float(np.min(growth / peak - 1.0))
    return cagr, sharpe, mdd


def paired_bootstrap(ch_eq: pd.DataFrame, base_eq: pd.DataFrame):
    aligned = ch_eq[["date", "equity"]].rename(columns={"equity": "ch"}).merge(
        base_eq[["date", "equity"]].rename(columns={"equity": "base"}), on="date", how="inner"
    ).sort_values("date")
    ch = pd.to_numeric(aligned["ch"], errors="coerce").pct_change().fillna(0.0).to_numpy(float)
    base = pd.to_numeric(aligned["base"], errors="coerce").pct_change().fillna(0.0).to_numpy(float)
    n = len(ch)
    if n < BOOTSTRAP_BLOCK * 2:
        raise RuntimeError("too few aligned returns for bootstrap")

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    blocks = int(math.ceil(n / BOOTSTRAP_BLOCK))
    max_start = n - BOOTSTRAP_BLOCK
    ch_sharpe, base_sharpe, ch_cagr, base_cagr, ch_mdd, base_mdd = [], [], [], [], [], []
    for _ in range(BOOTSTRAP_PATHS):
        starts = rng.integers(0, max_start + 1, size=blocks)
        idx = np.concatenate([np.arange(s, s + BOOTSTRAP_BLOCK) for s in starts])[:n]
        cm = _metrics(ch[idx])
        bm = _metrics(base[idx])
        ch_cagr.append(cm[0]); ch_sharpe.append(cm[1]); ch_mdd.append(cm[2])
        base_cagr.append(bm[0]); base_sharpe.append(bm[1]); base_mdd.append(bm[2])

    arrays = {name: np.asarray(values) for name, values in {
        "ch_cagr": ch_cagr, "base_cagr": base_cagr,
        "ch_sharpe": ch_sharpe, "base_sharpe": base_sharpe,
        "ch_mdd": ch_mdd, "base_mdd": base_mdd,
    }.items()}

    def quantiles(values):
        return {
            "p05": float(np.quantile(values, 0.05)),
            "p25": float(np.quantile(values, 0.25)),
            "median": float(np.quantile(values, 0.50)),
            "p95": float(np.quantile(values, 0.95)),
        }

    return {
        "paths": BOOTSTRAP_PATHS,
        "block_days": BOOTSTRAP_BLOCK,
        "seed": BOOTSTRAP_SEED,
        "challenger_cagr": quantiles(arrays["ch_cagr"]),
        "baseline_cagr": quantiles(arrays["base_cagr"]),
        "challenger_sharpe": quantiles(arrays["ch_sharpe"]),
        "baseline_sharpe": quantiles(arrays["base_sharpe"]),
        "challenger_mdd": quantiles(arrays["ch_mdd"]),
        "baseline_mdd": quantiles(arrays["base_mdd"]),
        "p_challenger_sharpe_gt_baseline": float(np.mean(arrays["ch_sharpe"] > arrays["base_sharpe"])),
        "p_challenger_cagr_gt_baseline": float(np.mean(arrays["ch_cagr"] > arrays["base_cagr"])),
        "median_sharpe_edge": float(np.median(arrays["ch_sharpe"] - arrays["base_sharpe"])),
        "median_cagr_edge": float(np.median(arrays["ch_cagr"] - arrays["base_cagr"])),
    }


def main():
    args = parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    artifact = Path(args.accepted_artifact_dir).resolve()

    if getattr(fdr, "__version__", None) not in (None, FDR_VERSION):
        raise RuntimeError(f"FinanceDataReader version drift: {fdr.__version__} != {FDR_VERSION}")

    base_events, base_sig, stored_summary, _ = load_base_events(artifact)
    frames = fetch_prices(args.test_start, args.end, out)
    ext_close, raw, volume = price_frames(frames, args.test_start, args.end)

    cfg = rpt.Config("20150101", args.test_start, args.end)
    base_tx, _, base_eq = ep.simulate_fractional_etf(base_events, raw, volume, cfg)
    base_sm = rpt.summarize(base_eq, base_tx, pd.DataFrame(), cfg)
    guard = validate_baseline(base_sm)
    stored_guard = {key: float(stored_summary[key] - KNOWN_84[key]) for key in KNOWN_84}
    if any(abs(value) > 1e-10 for value in stored_guard.values()):
        raise RuntimeError(f"stored accepted summary drift: {stored_guard}")
    print(f"[guard] accepted 84d baseline reproduced: {guard}", flush=True)

    events, signals, rolling_vol = build_ivol_events(ext_close, args.test_start, args.end)
    signals.to_csv(out / "ivol63_signals.csv", index=False, encoding="utf-8-sig")
    rolling_vol.to_csv(out / "rolling_vol_63d.csv", encoding="utf-8-sig")

    ch_tx, _, ch_eq = ep.simulate_fractional_etf(events, raw, volume, cfg)
    ch_sm = rpt.summarize(ch_eq, ch_tx, pd.DataFrame(), cfg)
    ch_tx.to_csv(out / "challenger_transactions.csv", index=False, encoding="utf-8-sig")
    ch_eq.to_csv(out / "challenger_equity_curve.csv", index=False, encoding="utf-8-sig")
    base_eq.to_csv(out / "baseline_resim_equity_curve.csv", index=False, encoding="utf-8-sig")
    base_sig.to_csv(out / "accepted_84d_signals_copy.csv", index=False, encoding="utf-8-sig")

    values, checks, primary_pass, ch_pre, base_pre, ch_sub, base_sub = evaluate_gates(
        ch_sm, base_sm, ch_eq, base_eq, cfg
    )

    weight_stats = {}
    for code in CODES:
        w = signals.loc[signals["stock_code"].eq(code), "target_weight"].astype(float)
        weight_stats[code] = {
            "mean": float(w.mean()),
            "min": float(w.min()),
            "max": float(w.max()),
        }

    result = {
        "research_id": RESEARCH_ID,
        "preregistered_comment_id": PREREG_COMMENT_ID,
        "methodology_label": "sequential same-history retrospective ETF risk-allocation challenger; NOT independent OOS",
        "accepted_artifact_source": {
            "run_id": 32492902475,
            "artifact_id": 9450776179,
            "digest": "sha256:52214865895e1b1a610e321ab7eadc345fa67fd638e90c7192b5393cdbc4b145",
        },
        "parameters": {
            "codes": CODES,
            "vol_lookback_sessions": VOL_LOOKBACK,
            "vol_ddof": 1,
            "rebalance": "calendar month-end common session, T+1",
            "weight_rule": "inverse volatility normalized to 100%",
            "cash_target": 0.0,
            "leverage": 1.0,
        },
        "baseline": base_sm,
        "challenger": ch_sm,
        "baseline_guard_diffs": guard,
        "stored_baseline_guard_diffs": stored_guard,
        "gate_values": values,
        "gate_checks": checks,
        "primary_pass": bool(primary_pass),
        "pre2025": {"baseline": base_pre, "challenger": ch_pre},
        "subperiods": {"baseline": base_sub, "challenger": ch_sub},
        "weight_stats": weight_stats,
        "n_ivol_signal_dates": int(signals["date"].nunique()),
        "operations": {
            "transaction_cost_krw": float(ch_sm["transaction_cost_krw"]),
            "transaction_cost_pct_initial": float(ch_sm["transaction_cost_krw"] / cfg.initial_capital),
            "gross_turnover_multiple": float(ch_sm["gross_traded_krw"] / cfg.initial_capital),
        },
        "gates": GATES,
    }

    if primary_pass:
        boot = paired_bootstrap(ch_eq, base_eq)
        boot_pass = bool(boot["p_challenger_sharpe_gt_baseline"] >= GATES["bootstrap_p_sharpe_better_min"])
        result["bootstrap"] = boot
        result["bootstrap_pass"] = boot_pass
        result["decision"] = "ADVANCE_TO_PROSPECTIVE" if boot_pass else "REJECT_BOOTSTRAP"
    else:
        result["bootstrap"] = None
        result["bootstrap_pass"] = None
        result["decision"] = "REJECT_PRIMARY_NO_RESCUE_TUNING"

    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame([
        {"strategy": "accepted_84d_baseline", **base_sm},
        {"strategy": "etf_ivol63", **ch_sm},
    ]).to_csv(out / "comparison.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
