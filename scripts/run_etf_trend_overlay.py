#!/usr/bin/env python3
"""Pre-registered ETF 10-month trend-overlay challenger.

Frozen in KR-security-test PR #1 comment 5376539768 before performance was observed.
Same-history exploratory challenger; a pass can only advance to robustness/prospective confirmation.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import replace
from pathlib import Path

import FinanceDataReader as fdr
import numpy as np
import pandas as pd

import run_portable_tournament as rpt
import run_personal_quant_baseline as pq
import run_etf_proxy_baseline as ep
import run_etf_rebalance_robustness as er
from run_long_reversal_challenger import _register_corrected_mom36


CODES = ["226490", "229200"]
ETF_CANDIDATE = {"codes": CODES, "mode": "market_split"}
PREREG_COMMENT_ID = 5376539768
FDR_VERSION = "0.9.201"
SMA_MONTHS = 10
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
    "sharpe_improvement_min": 0.10,
    "mdd_improvement_min": 0.05,
    "cagr_gap_min": -0.02,
    "pre2025_sharpe_improvement_min": 0.10,
    "max_bad_subperiods": 1,
    "bad_subperiod_sharpe_gap": -0.15,
    "bootstrap_p_sharpe_better_min": 0.60,
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--alphakrx-root", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--feature-start", required=True)
    p.add_argument("--test-start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--output", default="outputs/etf_trend_overlay")
    return p.parse_args()


def extended_price_frames(test_start: str, end: str, out: Path):
    start = (pd.Timestamp(test_start) - pd.Timedelta(days=500)).strftime("%Y-%m-%d")
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
        audits.append({
            "stock_code": code,
            "rows": len(df),
            "date_min": str(df["date"].min()),
            "date_max": str(df["date"].max()),
            "max_abs_daily_move": float(move.max(skipna=True)),
            "rows_abs_move_gt_30pct": int((move > 0.30 + 1e-12).sum()),
        })
        df.to_csv(out / f"etf_extended_{code}.csv", index=False, encoding="utf-8-sig")
        frames[code] = df
    audit = pd.DataFrame(audits)
    audit.to_csv(out / "etf_extended_data_audit.csv", index=False, encoding="utf-8-sig")
    if (audit["rows_abs_move_gt_30pct"] > 0).any():
        raise RuntimeError(f"ETF extended-price integrity failure: {audit.to_dict('records')}")
    return frames


def close_volume_frames(frames: dict[str, pd.DataFrame], test_start: str, end: str):
    ext_close = None
    raw = None
    volume = None
    for code, df in frames.items():
        x = df.set_index("date")
        c_ext = x[["Close"]].rename(columns={"Close": code})
        ext_close = c_ext if ext_close is None else ext_close.join(c_ext, how="outer")
        y = x[(x.index >= test_start) & (x.index <= end)]
        c = y[["Close"]].rename(columns={"Close": code})
        v = y[["Volume"]].rename(columns={"Volume": code})
        raw = c if raw is None else raw.join(c, how="outer")
        volume = v if volume is None else volume.join(v, how="outer")
    assert ext_close is not None and raw is not None and volume is not None
    return ext_close.sort_index(), raw.sort_index(), volume.reindex(raw.index).sort_index()


def month_end_states(ext_close: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, dict[str, bool]]]:
    common = ext_close[CODES].dropna(how="any").copy()
    if common.empty:
        raise RuntimeError("no common ETF closes for trend signal")
    idx = pd.to_datetime(common.index, format="%Y%m%d", errors="coerce")
    common = common.assign(_dt=idx).dropna(subset=["_dt"])
    common["_month"] = common["_dt"].dt.to_period("M")
    monthly = common.groupby("_month", sort=True).tail(1).copy()
    monthly = monthly.sort_values("_dt")
    states: dict[str, dict[str, bool]] = {}
    for code in CODES:
        monthly[f"{code}_sma10"] = monthly[code].rolling(SMA_MONTHS, min_periods=SMA_MONTHS).mean()
        monthly[f"{code}_trend_on"] = monthly[code] > monthly[f"{code}_sma10"]
    for _, row in monthly.iterrows():
        if any(pd.isna(row[f"{code}_sma10"]) for code in CODES):
            continue
        d = row["_dt"].strftime("%Y%m%d")
        states[d] = {code: bool(row[f"{code}_trend_on"]) for code in CODES}
    cols = ["_dt", *CODES, *[f"{c}_sma10" for c in CODES], *[f"{c}_trend_on" for c in CODES]]
    return monthly[cols].copy(), states


def latest_state(states: dict[str, dict[str, bool]], signal_date: str) -> dict[str, bool]:
    eligible = [d for d in states if d <= signal_date]
    if not eligible:
        raise RuntimeError(f"no completed 10-month trend state by {signal_date}")
    return states[max(eligible)]


def overlay_events(panel: pd.DataFrame, base_dates: list[str], states: dict[str, dict[str, bool]], test_start: str, end: str):
    base_map = {}
    for d in base_dates:
        split = ep.market_split_weights(panel, d)
        base_map[d] = pd.Series({CODES[0]: split["kospi"], CODES[1]: split["kosdaq"]}, dtype=float)

    month_dates = sorted(d for d in states if test_start <= d <= end)
    event_dates = sorted(set(base_dates) | set(month_dates))
    current_base = None
    rows = []
    events = []
    for d in event_dates:
        if d in base_map:
            current_base = base_map[d]
        if current_base is None:
            continue
        state = latest_state(states, d)
        target = pd.Series({code: float(current_base.get(code, 0.0)) * float(state[code]) for code in CODES}, dtype=float)
        target = target[target > 0]
        events.append((d, target, None))
        for code in CODES:
            rows.append({
                "date": d,
                "stock_code": code,
                "base_weight": float(current_base.get(code, 0.0)),
                "trend_on": bool(state[code]),
                "target_weight": float(target.get(code, 0.0)),
                "strategic_cash_weight": float(1.0 - target.sum()),
                "event_type": "+".join(x for x, ok in (("base84", d in base_map), ("month_end", d in month_dates)) if ok),
            })
    return events, pd.DataFrame(rows)


def period_stats(eq: pd.DataFrame, start: str, end: str) -> dict[str, float]:
    e = eq[(eq["date"] >= start) & (eq["date"] <= end)].copy()
    if len(e) < 2:
        return {"return": math.nan, "cagr": math.nan, "sharpe": math.nan, "mdd": math.nan}
    equity = pd.to_numeric(e["equity"], errors="coerce")
    r = equity.pct_change().fillna(0.0)
    sd = float(r.std(ddof=1))
    years = max((pd.to_datetime(e["date"].iloc[-1]) - pd.to_datetime(e["date"].iloc[0])).days / 365.25, 1 / 365.25)
    total = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0)
    return {
        "return": total,
        "cagr": cagr,
        "sharpe": float(np.sqrt(252.0) * r.mean() / sd) if sd > 0 and np.isfinite(sd) else math.nan,
        "mdd": float((equity / equity.cummax() - 1.0).min()),
    }


def validate_baseline(sm: dict):
    diffs = {k: float(sm[k] - v) for k, v in KNOWN_84.items()}
    if any(abs(v) > 1e-10 for v in diffs.values()):
        raise RuntimeError(f"accepted 84d baseline drift: {diffs}")
    return diffs


def primary_gates(ch: dict, base: dict, ch_eq: pd.DataFrame, base_eq: pd.DataFrame):
    pre_ch = period_stats(ch_eq, "20180101", "20241231")
    pre_base = period_stats(base_eq, "20180101", "20241231")
    sub_ch = pq.subperiods(ch_eq)
    sub_base = pq.subperiods(base_eq)
    bad = 0
    for period in ("2018_2021", "2022_2024", "2025_2026"):
        c = float(sub_ch[period]["sharpe"])
        b = float(sub_base[period]["sharpe"])
        if np.isfinite(c) and np.isfinite(b) and c - b < GATES["bad_subperiod_sharpe_gap"]:
            bad += 1
    values = {
        "full_sharpe_improvement": float(ch["sharpe"] - base["sharpe"]),
        "mdd_improvement": float(ch["max_drawdown"] - base["max_drawdown"]),
        "calmar_gap": float(ch["calmar"] - base["calmar"]),
        "cagr_gap": float(ch["cagr"] - base["cagr"]),
        "pre2025_sharpe_improvement": float(pre_ch["sharpe"] - pre_base["sharpe"]),
        "bad_subperiod_count": int(bad),
    }
    checks = {
        "full_sharpe": values["full_sharpe_improvement"] >= GATES["sharpe_improvement_min"],
        "mdd": values["mdd_improvement"] >= GATES["mdd_improvement_min"],
        "calmar": values["calmar_gap"] >= 0.0,
        "cagr": values["cagr_gap"] >= GATES["cagr_gap_min"],
        "pre2025_sharpe": values["pre2025_sharpe_improvement"] >= GATES["pre2025_sharpe_improvement_min"],
        "subperiod_stability": bad <= GATES["max_bad_subperiods"],
    }
    return values, checks, bool(all(checks.values())), pre_ch, pre_base, sub_ch, sub_base


def aligned_returns(ch_eq: pd.DataFrame, base_eq: pd.DataFrame):
    a = ch_eq[["date", "equity"]].rename(columns={"equity": "ch"})
    b = base_eq[["date", "equity"]].rename(columns={"equity": "base"})
    x = a.merge(b, on="date", how="inner").sort_values("date")
    x["ch_r"] = pd.to_numeric(x["ch"], errors="coerce").pct_change().fillna(0.0)
    x["base_r"] = pd.to_numeric(x["base"], errors="coerce").pct_change().fillna(0.0)
    return x[["date", "ch_r", "base_r"]].reset_index(drop=True)


def one_path_metrics(r: np.ndarray):
    growth = np.cumprod(1.0 + r)
    total = float(growth[-1]) if len(growth) else 1.0
    cagr = total ** (252.0 / len(r)) - 1.0 if len(r) else math.nan
    sd = float(np.std(r, ddof=1)) if len(r) > 1 else math.nan
    sharpe = float(np.sqrt(252.0) * np.mean(r) / sd) if np.isfinite(sd) and sd > 0 else math.nan
    peak = np.maximum.accumulate(growth)
    mdd = float(np.min(growth / peak - 1.0)) if len(growth) else math.nan
    return cagr, sharpe, mdd


def paired_bootstrap(ret: pd.DataFrame):
    ch = ret["ch_r"].to_numpy(dtype=float)
    base = ret["base_r"].to_numpy(dtype=float)
    n = len(ch)
    if n < BOOTSTRAP_BLOCK * 2:
        raise RuntimeError("too few daily returns for paired bootstrap")
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    out = {k: [] for k in ("ch_cagr", "base_cagr", "ch_sharpe", "base_sharpe", "ch_mdd", "base_mdd")}
    n_blocks = int(math.ceil(n / BOOTSTRAP_BLOCK))
    max_start = n - BOOTSTRAP_BLOCK
    for _ in range(BOOTSTRAP_PATHS):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + BOOTSTRAP_BLOCK) for s in starts])[:n]
        cm = one_path_metrics(ch[idx])
        bm = one_path_metrics(base[idx])
        for key, val in zip(("ch_cagr", "ch_sharpe", "ch_mdd"), cm):
            out[key].append(val)
        for key, val in zip(("base_cagr", "base_sharpe", "base_mdd"), bm):
            out[key].append(val)
    arrays = {k: np.asarray(v, dtype=float) for k, v in out.items()}
    def q(a):
        return {"p05": float(np.quantile(a, 0.05)), "p25": float(np.quantile(a, 0.25)), "median": float(np.quantile(a, 0.50)), "p95": float(np.quantile(a, 0.95))}
    return {
        "paths": BOOTSTRAP_PATHS,
        "block_days": BOOTSTRAP_BLOCK,
        "seed": BOOTSTRAP_SEED,
        "challenger_cagr": q(arrays["ch_cagr"]),
        "baseline_cagr": q(arrays["base_cagr"]),
        "challenger_sharpe": q(arrays["ch_sharpe"]),
        "baseline_sharpe": q(arrays["base_sharpe"]),
        "challenger_mdd": q(arrays["ch_mdd"]),
        "baseline_mdd": q(arrays["base_mdd"]),
        "p_challenger_sharpe_gt_baseline": float(np.mean(arrays["ch_sharpe"] > arrays["base_sharpe"])),
        "p_challenger_cagr_gt_baseline": float(np.mean(arrays["ch_cagr"] > arrays["base_cagr"])),
        "median_sharpe_edge": float(np.median(arrays["ch_sharpe"] - arrays["base_sharpe"])),
        "median_cagr_edge": float(np.median(arrays["ch_cagr"] - arrays["base_cagr"])),
    }


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

    cfg = rpt.Config(a.feature_start, a.test_start, a.end)
    sim_cfg = replace(cfg, initial_capital=100_000_000.0)

    frames = extended_price_frames(cfg.test_start, cfg.end, out)
    ext_close, raw, volume = close_volume_frames(frames, cfg.test_start, cfg.end)
    monthly, states = month_end_states(ext_close)
    monthly.to_csv(out / "monthly_trend_states.csv", index=False, encoding="utf-8-sig")

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

    base_dates = er.cadence_dates(panel, cfg.test_start, cfg.end, 84)
    base_events, base_sig = ep.candidate_events(panel, base_dates, ETF_CANDIDATE)
    base_tx, _, base_eq = ep.simulate_fractional_etf(base_events, raw, volume, sim_cfg)
    base_sm = rpt.summarize(base_eq, base_tx, pd.DataFrame(), sim_cfg)
    base_guard = validate_baseline(base_sm)
    print(f"[guard] accepted 84d baseline reproduced: {base_guard}", flush=True)

    events, signal_rows = overlay_events(panel, base_dates, states, cfg.test_start, cfg.end)
    signal_rows.to_csv(out / "trend_overlay_signals.csv", index=False, encoding="utf-8-sig")
    ch_tx, _, ch_eq = ep.simulate_fractional_etf(events, raw, volume, sim_cfg)
    ch_sm = rpt.summarize(ch_eq, ch_tx, pd.DataFrame(), sim_cfg)
    ch_tx.to_csv(out / "challenger_transactions.csv", index=False, encoding="utf-8-sig")
    ch_eq.to_csv(out / "challenger_equity_curve.csv", index=False, encoding="utf-8-sig")
    base_eq.to_csv(out / "baseline_84d_equity_curve.csv", index=False, encoding="utf-8-sig")

    values, checks, primary_pass, pre_ch, pre_base, sub_ch, sub_base = primary_gates(ch_sm, base_sm, ch_eq, base_eq)
    result = {
        "research": "ETF 10-month month-end per-leg trend overlay",
        "preregistered_comment_id": PREREG_COMMENT_ID,
        "label": "same-history exploratory challenger; not independent OOS",
        "baseline": base_sm,
        "challenger": ch_sm,
        "gate_values": values,
        "gate_checks": checks,
        "primary_pass": primary_pass,
        "pre2025": {"baseline": pre_base, "challenger": pre_ch},
        "subperiods": {"baseline": sub_base, "challenger": sub_ch},
        "n_base_rebalances": len(base_dates),
        "n_overlay_events": len(events),
        "n_month_end_states_in_test": sum(cfg.test_start <= d <= cfg.end for d in states),
        "mean_strategic_cash_weight": float(signal_rows.drop_duplicates("date")["strategic_cash_weight"].mean()),
        "gates": GATES,
    }

    if primary_pass:
        print("[gate] PRIMARY PASS -> paired bootstrap", flush=True)
        boot = paired_bootstrap(aligned_returns(ch_eq, base_eq))
        result["bootstrap"] = boot
        result["bootstrap_pass"] = bool(boot["p_challenger_sharpe_gt_baseline"] >= GATES["bootstrap_p_sharpe_better_min"])
        result["decision"] = "ADVANCE_TO_PROSPECTIVE" if result["bootstrap_pass"] else "REJECT_BOOTSTRAP"
    else:
        result["bootstrap"] = None
        result["bootstrap_pass"] = None
        result["decision"] = "REJECT_PRIMARY_NO_RESCUE_TUNING"

    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame([
        {"strategy": "accepted_84d_baseline", **base_sm},
        {"strategy": "trend_overlay_10m", **ch_sm},
    ]).to_csv(out / "comparison.csv", index=False, encoding="utf-8-sig")

    print("\n=== ETF 10M Trend Overlay ===", flush=True)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
