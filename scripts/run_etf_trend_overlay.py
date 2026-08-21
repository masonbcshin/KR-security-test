#!/usr/bin/env python3
"""Pre-registered ETF 10-month trend-overlay challenger.

Frozen in PR #1 comment 5376539768 before performance was observed.
Implementation tightened pre-result in PR #2 comment 5376557554: the accepted
84d artifact is the immutable base-weight input; no PIT DB is rebuilt here.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import FinanceDataReader as fdr
import numpy as np
import pandas as pd

import run_portable_tournament as rpt
import run_personal_quant_baseline as pq
import run_etf_proxy_baseline as ep

CODES = ["226490", "229200"]
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
    p.add_argument("--accepted-artifact-dir", required=True)
    p.add_argument("--test-start", default="20180101")
    p.add_argument("--end", default="20260320")
    p.add_argument("--output", default="outputs/etf_trend_overlay")
    return p.parse_args()


def load_base_events(root: Path):
    sig_path = root / "cadence_84d" / "signals.csv"
    if not sig_path.exists():
        raise RuntimeError(f"accepted 84d signals missing: {sig_path}")
    sig = pd.read_csv(sig_path, dtype={"date": str, "stock_code": str})
    sig["date"] = sig["date"].astype(str).str.zfill(8)
    sig["stock_code"] = sig["stock_code"].astype(str).str.zfill(6)
    sig["target_weight"] = pd.to_numeric(sig["target_weight"], errors="raise")
    if set(sig["stock_code"].unique()) != set(CODES):
        raise RuntimeError(f"accepted signals contain unexpected codes: {sorted(sig['stock_code'].unique())}")
    events = []
    base_map = {}
    for d, day in sig.groupby("date", sort=True):
        w = day.set_index("stock_code")["target_weight"].astype(float).reindex(CODES).fillna(0.0)
        if abs(float(w.sum()) - 1.0) > 1e-10:
            raise RuntimeError(f"accepted base weights do not sum to 1 on {d}: {w.to_dict()}")
        base_map[str(d)] = w
        events.append((str(d), w, None))
    return events, base_map, sig


def fetch_prices(test_start: str, end: str, out: Path):
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
            "rows": int(len(df)),
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


def month_end_states(ext_close: pd.DataFrame):
    common = ext_close[CODES].dropna(how="any").copy()
    common["_dt"] = pd.to_datetime(common.index, format="%Y%m%d", errors="coerce")
    common = common.dropna(subset=["_dt"])
    common["_month"] = common["_dt"].dt.to_period("M")
    monthly = common.groupby("_month", sort=True).tail(1).sort_values("_dt").copy()
    states = {}
    for code in CODES:
        monthly[f"{code}_sma10"] = monthly[code].rolling(SMA_MONTHS, min_periods=SMA_MONTHS).mean()
        monthly[f"{code}_trend_on"] = monthly[code] > monthly[f"{code}_sma10"]
    for _, row in monthly.iterrows():
        if any(pd.isna(row[f"{c}_sma10"]) for c in CODES):
            continue
        d = row["_dt"].strftime("%Y%m%d")
        states[d] = {c: bool(row[f"{c}_trend_on"]) for c in CODES}
    return monthly, states


def state_at(states, d: str):
    candidates = [x for x in states if x <= d]
    if not candidates:
        raise RuntimeError(f"no completed 10m trend state by {d}")
    return states[max(candidates)]


def build_overlay_events(base_map, states, test_start: str, end: str):
    base_dates = sorted(base_map)
    month_dates = sorted(d for d in states if test_start <= d <= end)
    dates = sorted(set(base_dates) | set(month_dates))
    current = None
    events, rows = [], []
    for d in dates:
        if d in base_map:
            current = base_map[d]
        if current is None:
            continue
        st = state_at(states, d)
        target = pd.Series({c: float(current[c]) * float(st[c]) for c in CODES}, dtype=float)
        target = target[target > 0.0]
        events.append((d, target, None))
        strategic_cash = float(1.0 - target.sum())
        for c in CODES:
            rows.append({
                "date": d,
                "stock_code": c,
                "base_weight": float(current[c]),
                "trend_on": bool(st[c]),
                "target_weight": float(target.get(c, 0.0)),
                "strategic_cash_weight": strategic_cash,
                "event_type": "+".join(k for k, yes in (("base84", d in base_map), ("month_end", d in month_dates)) if yes),
            })
    return events, pd.DataFrame(rows)


def validate_baseline(sm: dict):
    diffs = {k: float(sm[k] - v) for k, v in KNOWN_84.items()}
    if any(abs(v) > 1e-10 for v in diffs.values()):
        raise RuntimeError(f"accepted 84d baseline drift: {diffs}")
    return diffs


def period_stats(eq, start: str, end: str):
    e = eq[(eq["date"] >= start) & (eq["date"] <= end)].copy()
    if len(e) < 2:
        return {"return": math.nan, "cagr": math.nan, "sharpe": math.nan, "mdd": math.nan}
    equity = pd.to_numeric(e["equity"], errors="coerce")
    r = equity.pct_change().fillna(0.0)
    sd = float(r.std(ddof=1))
    dt0, dt1 = pd.to_datetime(e["date"].iloc[0]), pd.to_datetime(e["date"].iloc[-1])
    years = max((dt1 - dt0).days / 365.25, 1 / 365.25)
    total = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    return {
        "return": total,
        "cagr": float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0),
        "sharpe": float(np.sqrt(252.0) * r.mean() / sd) if sd > 0 and np.isfinite(sd) else math.nan,
        "mdd": float((equity / equity.cummax() - 1.0).min()),
    }


def evaluate_gates(ch, base, ch_eq, base_eq):
    pre_ch = period_stats(ch_eq, "20180101", "20241231")
    pre_base = period_stats(base_eq, "20180101", "20241231")
    sub_ch, sub_base = pq.subperiods(ch_eq), pq.subperiods(base_eq)
    bad = 0
    for period in ("2018_2021", "2022_2024", "2025_2026"):
        if float(sub_ch[period]["sharpe"]) - float(sub_base[period]["sharpe"]) < GATES["bad_subperiod_sharpe_gap"]:
            bad += 1
    vals = {
        "full_sharpe_improvement": float(ch["sharpe"] - base["sharpe"]),
        "mdd_improvement": float(ch["max_drawdown"] - base["max_drawdown"]),
        "calmar_gap": float(ch["calmar"] - base["calmar"]),
        "cagr_gap": float(ch["cagr"] - base["cagr"]),
        "pre2025_sharpe_improvement": float(pre_ch["sharpe"] - pre_base["sharpe"]),
        "bad_subperiod_count": int(bad),
    }
    checks = {
        "full_sharpe": vals["full_sharpe_improvement"] >= GATES["sharpe_improvement_min"],
        "mdd": vals["mdd_improvement"] >= GATES["mdd_improvement_min"],
        "calmar": vals["calmar_gap"] >= 0,
        "cagr": vals["cagr_gap"] >= GATES["cagr_gap_min"],
        "pre2025_sharpe": vals["pre2025_sharpe_improvement"] >= GATES["pre2025_sharpe_improvement_min"],
        "subperiod_stability": bad <= GATES["max_bad_subperiods"],
    }
    return vals, checks, all(checks.values()), pre_ch, pre_base, sub_ch, sub_base


def metrics_from_returns(r: np.ndarray):
    growth = np.cumprod(1.0 + r)
    cagr = float(growth[-1] ** (252.0 / len(r)) - 1.0)
    sd = float(np.std(r, ddof=1))
    sharpe = float(np.sqrt(252.0) * np.mean(r) / sd) if sd > 0 else math.nan
    peak = np.maximum.accumulate(growth)
    mdd = float(np.min(growth / peak - 1.0))
    return cagr, sharpe, mdd


def paired_bootstrap(ch_eq, base_eq):
    x = ch_eq[["date", "equity"]].rename(columns={"equity": "ch"}).merge(
        base_eq[["date", "equity"]].rename(columns={"equity": "base"}), on="date", how="inner"
    ).sort_values("date")
    ch = pd.to_numeric(x["ch"], errors="coerce").pct_change().fillna(0.0).to_numpy(float)
    base = pd.to_numeric(x["base"], errors="coerce").pct_change().fillna(0.0).to_numpy(float)
    n = len(ch)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    blocks = int(math.ceil(n / BOOTSTRAP_BLOCK))
    max_start = n - BOOTSTRAP_BLOCK
    ch_s, base_s, ch_c, base_c, ch_m, base_m = [], [], [], [], [], []
    for _ in range(BOOTSTRAP_PATHS):
        starts = rng.integers(0, max_start + 1, size=blocks)
        idx = np.concatenate([np.arange(s, s + BOOTSTRAP_BLOCK) for s in starts])[:n]
        cm, bm = metrics_from_returns(ch[idx]), metrics_from_returns(base[idx])
        ch_c.append(cm[0]); ch_s.append(cm[1]); ch_m.append(cm[2])
        base_c.append(bm[0]); base_s.append(bm[1]); base_m.append(bm[2])
    arrays = {k: np.asarray(v) for k, v in {"ch_cagr":ch_c,"base_cagr":base_c,"ch_sharpe":ch_s,"base_sharpe":base_s,"ch_mdd":ch_m,"base_mdd":base_m}.items()}
    def q(a):
        return {"p05":float(np.quantile(a,.05)),"p25":float(np.quantile(a,.25)),"median":float(np.quantile(a,.5)),"p95":float(np.quantile(a,.95))}
    return {
        "paths": BOOTSTRAP_PATHS, "block_days": BOOTSTRAP_BLOCK, "seed": BOOTSTRAP_SEED,
        "challenger_cagr": q(arrays["ch_cagr"]), "baseline_cagr": q(arrays["base_cagr"]),
        "challenger_sharpe": q(arrays["ch_sharpe"]), "baseline_sharpe": q(arrays["base_sharpe"]),
        "challenger_mdd": q(arrays["ch_mdd"]), "baseline_mdd": q(arrays["base_mdd"]),
        "p_challenger_sharpe_gt_baseline": float(np.mean(arrays["ch_sharpe"] > arrays["base_sharpe"])),
        "p_challenger_cagr_gt_baseline": float(np.mean(arrays["ch_cagr"] > arrays["base_cagr"])),
        "median_sharpe_edge": float(np.median(arrays["ch_sharpe"] - arrays["base_sharpe"])),
        "median_cagr_edge": float(np.median(arrays["ch_cagr"] - arrays["base_cagr"])),
    }


def main():
    a = parse_args()
    artifact = Path(a.accepted_artifact_dir).resolve()
    out = Path(a.output).resolve(); out.mkdir(parents=True, exist_ok=True)
    if getattr(fdr, "__version__", None) not in (None, FDR_VERSION):
        raise RuntimeError(f"FinanceDataReader version drift: {fdr.__version__} != {FDR_VERSION}")

    base_events, base_map, base_sig = load_base_events(artifact)
    frames = fetch_prices(a.test_start, a.end, out)
    ext_close, raw, volume = price_frames(frames, a.test_start, a.end)
    monthly, states = month_end_states(ext_close)
    monthly.to_csv(out / "monthly_trend_states.csv", index=False, encoding="utf-8-sig")

    cfg = rpt.Config("20150101", a.test_start, a.end)
    base_tx, _, base_eq = ep.simulate_fractional_etf(base_events, raw, volume, cfg)
    base_sm = rpt.summarize(base_eq, base_tx, pd.DataFrame(), cfg)
    guard = validate_baseline(base_sm)
    print(f"[guard] accepted 84d baseline reproduced: {guard}", flush=True)

    events, signal_rows = build_overlay_events(base_map, states, a.test_start, a.end)
    ch_tx, _, ch_eq = ep.simulate_fractional_etf(events, raw, volume, cfg)
    ch_sm = rpt.summarize(ch_eq, ch_tx, pd.DataFrame(), cfg)
    signal_rows.to_csv(out / "trend_overlay_signals.csv", index=False, encoding="utf-8-sig")
    ch_tx.to_csv(out / "challenger_transactions.csv", index=False, encoding="utf-8-sig")
    ch_eq.to_csv(out / "challenger_equity_curve.csv", index=False, encoding="utf-8-sig")
    base_eq.to_csv(out / "baseline_resim_equity_curve.csv", index=False, encoding="utf-8-sig")
    base_sig.to_csv(out / "accepted_84d_signals_copy.csv", index=False, encoding="utf-8-sig")

    vals, checks, primary_pass, pre_ch, pre_base, sub_ch, sub_base = evaluate_gates(ch_sm, base_sm, ch_eq, base_eq)
    result = {
        "research": "ETF 10-month month-end per-leg trend overlay", "preregistered_comment_id": PREREG_COMMENT_ID,
        "methodology_label": "same-history exploratory challenger; NOT independent OOS",
        "accepted_artifact_source": {"run_id":32492902475,"artifact_id":9450776179,"digest":"sha256:52214865895e1b1a610e321ab7eadc345fa67fd638e90c7192b5393cdbc4b145"},
        "baseline": base_sm, "challenger": ch_sm, "baseline_guard_diffs": guard,
        "gate_values": vals, "gate_checks": checks, "primary_pass": bool(primary_pass),
        "pre2025": {"baseline":pre_base,"challenger":pre_ch}, "subperiods":{"baseline":sub_base,"challenger":sub_ch},
        "n_base_rebalances": len(base_map), "n_overlay_events": len(events),
        "mean_strategic_cash_weight": float(signal_rows.drop_duplicates("date")["strategic_cash_weight"].mean()),
        "gates": GATES,
    }
    if primary_pass:
        boot = paired_bootstrap(ch_eq, base_eq)
        result["bootstrap"] = boot
        result["bootstrap_pass"] = bool(boot["p_challenger_sharpe_gt_baseline"] >= GATES["bootstrap_p_sharpe_better_min"])
        result["decision"] = "ADVANCE_TO_PROSPECTIVE" if result["bootstrap_pass"] else "REJECT_BOOTSTRAP"
    else:
        result["bootstrap"] = None; result["bootstrap_pass"] = None
        result["decision"] = "REJECT_PRIMARY_NO_RESCUE_TUNING"
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame([{"strategy":"accepted_84d_baseline",**base_sm},{"strategy":"trend_overlay_10m",**ch_sm}]).to_csv(out / "comparison.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
