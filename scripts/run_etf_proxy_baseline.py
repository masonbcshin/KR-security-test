#!/usr/bin/env python3
"""Pre-registered ETF/index-proxy translation for an individual Korean quant.

This is not alpha optimization. It tests whether the authoritative fractional
full-universe cap benchmark can be approximated by one or two Korean-listed
broad-market ETFs with materially lower operational complexity.

Frozen in PR #1 comment 5364956891 before ETF performance was inspected.
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
from run_long_reversal_challenger import _register_corrected_mom36


ETF_META = {
    "069500": {"label": "KODEX 200", "leg": "kospi"},
    "226490": {"label": "KODEX KOSPI", "leg": "kospi"},
    "229200": {"label": "KODEX KOSDAQ150", "leg": "kosdaq"},
}

CANDIDATES = {
    "kodex_kospi": {"codes": ["226490"], "mode": "single"},
    "kodex_200": {"codes": ["069500"], "mode": "single"},
    "kodex_kospi_kq150_split": {"codes": ["226490", "229200"], "mode": "market_split"},
    "kodex_200_kq150_split": {"codes": ["069500", "229200"], "mode": "market_split"},
}

CAPITALS = [10_000_000.0, 30_000_000.0, 100_000_000.0]

FIDELITY_GATES = {
    "tracking_error_max": 0.05,
    "abs_cagr_gap_max": 0.015,
    "abs_sharpe_gap_max": 0.10,
    "abs_mdd_gap_max": 0.05,
    "avg_cash_ratio_max": 0.05,
    "max_cash_ratio_max": 0.15,
    "coverage_min": 0.99,
    "max_abs_daily_move": 0.30,
}

PREREG_COMMENT_ID = 5364956891
FDR_VERSION = "0.9.201"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--alphakrx-root", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--feature-start", required=True)
    p.add_argument("--test-start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--output", default="outputs/etf_proxy")
    return p.parse_args()


def fetch_etf_prices(test_start: str, end: str, out: Path):
    start = (pd.Timestamp(test_start) - pd.Timedelta(days=40)).strftime("%Y-%m-%d")
    end_iso = pd.Timestamp(end).strftime("%Y-%m-%d")
    frames = {}
    audit_rows = []
    for code, meta in ETF_META.items():
        df = fdr.DataReader(f"NAVER:{code}", start, end_iso).copy()
        if df.empty:
            raise RuntimeError(f"ETF data empty for {code} {meta['label']}")
        df = df.reset_index()
        if "Date" not in df.columns:
            df = df.rename(columns={df.columns[0]: "Date"})
        df["date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y%m%d")
        for c in ["Open", "High", "Low", "Close", "Volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["date", "Close"]).sort_values("date").drop_duplicates("date")
        df = df[["date", "Open", "High", "Low", "Close", "Volume"]].reset_index(drop=True)
        move = df["Close"].pct_change().abs()
        audit_rows.append({
            "stock_code": code,
            "label": meta["label"],
            "rows": int(len(df)),
            "date_min": str(df["date"].min()),
            "date_max": str(df["date"].max()),
            "max_abs_daily_move": float(move.max(skipna=True)),
            "rows_abs_move_gt_30pct": int((move > FIDELITY_GATES["max_abs_daily_move"] + 1e-12).sum()),
            "zero_or_bad_close_rows": int((~np.isfinite(df["Close"]) | (df["Close"] <= 0)).sum()),
            "zero_volume_rows": int((df["Volume"].fillna(0) <= 0).sum()),
        })
        df.to_csv(out / f"etf_{code}.csv", index=False, encoding="utf-8-sig")
        frames[code] = df
    audit = pd.DataFrame(audit_rows)
    audit.to_csv(out / "etf_data_audit.csv", index=False, encoding="utf-8-sig")
    if (audit["rows_abs_move_gt_30pct"] > 0).any():
        bad = audit[audit["rows_abs_move_gt_30pct"] > 0][["stock_code", "label", "max_abs_daily_move"]]
        raise RuntimeError(f"ETF data integrity: unexplained >30% one-day move detected: {bad.to_dict('records')}")
    return frames, audit


def common_price_frames(frames: dict[str, pd.DataFrame], test_start: str, end: str):
    raw = None
    volume = None
    for code, df in frames.items():
        x = df[(df["date"] >= test_start) & (df["date"] <= end)].set_index("date")
        c = x[["Close"]].rename(columns={"Close": code})
        v = x[["Volume"]].rename(columns={"Volume": code})
        raw = c if raw is None else raw.join(c, how="outer")
        volume = v if volume is None else volume.join(v, how="outer")
    return raw.sort_index(), volume.reindex(raw.index).sort_index()


def market_split_weights(panel: pd.DataFrame, date: str):
    day = panel[panel["date"].eq(date)].copy()
    day["market_cap"] = pd.to_numeric(day["market_cap"], errors="coerce")
    day = day[np.isfinite(day["market_cap"]) & (day["market_cap"] > 0)]
    sums = day.groupby("market_type")["market_cap"].sum()
    k = float(sums.get("kospi", 0.0))
    q = float(sums.get("kosdaq", 0.0))
    total = k + q
    if total <= 0:
        raise RuntimeError(f"no market cap split available on {date}")
    return {"kospi": k / total, "kosdaq": q / total}


def candidate_events(panel: pd.DataFrame, rebal_dates: list[str], candidate: dict):
    rows = []
    events = []
    codes = candidate["codes"]
    for d in rebal_dates:
        if candidate["mode"] == "single":
            weights = pd.Series({codes[0]: 1.0}, dtype=float)
        else:
            split = market_split_weights(panel, d)
            weights = pd.Series({codes[0]: split["kospi"], codes[1]: split["kosdaq"]}, dtype=float)
        weights = weights[weights > 0]
        weights = weights / weights.sum()
        events.append((d, weights, None))
        for code, w in weights.items():
            rows.append({"date": d, "stock_code": code, "label": ETF_META[code]["label"], "target_weight": float(w)})
    return events, pd.DataFrame(rows)


def simulate_fractional_etf(events, raw: pd.DataFrame, volume: pd.DataFrame, cfg):
    raw = raw.loc[(raw.index >= cfg.test_start) & (raw.index <= cfg.end)].copy()
    volume = volume.reindex(raw.index)
    if raw.empty:
        raise RuntimeError("ETF simulator has no prices")
    tradable = volume.fillna(0).gt(0) & raw.notna() & raw.gt(0)
    mark = raw.ffill()
    dates = list(mark.index)
    by_exec = {}
    for signal_date, weights, _ in events:
        possible = [d for d in dates if d > signal_date]
        if possible:
            by_exec.setdefault(possible[0], []).append((signal_date, weights.astype(float)))

    cash = float(cfg.initial_capital)
    pos = {}
    tx = []
    eq = []

    def equity(d):
        return cash + sum(sh * float(mark.at[d, c]) for c, sh in pos.items() if c in mark.columns and pd.notna(mark.at[d, c]))

    for d in dates:
        for signal, weights in by_exec.get(d, []):
            eq0 = equity(d)
            desired = {}
            for c, w in weights.items():
                if c in raw.columns and bool(tradable.at[d, c]) and pd.notna(raw.at[d, c]) and raw.at[d, c] > 0:
                    desired[c] = eq0 * float(w) / float(raw.at[d, c])
                elif c in pos:
                    desired[c] = pos[c]
            allc = set(pos) | set(desired)
            for c in sorted(allc):
                old, new = float(pos.get(c, 0.0)), float(desired.get(c, 0.0))
                if new >= old - 1e-12:
                    continue
                if c not in tradable.columns or not bool(tradable.at[d, c]):
                    continue
                q = old - new
                p = float(raw.at[d, c])
                gross = q * p
                cost = gross * cfg.sell_cost
                cash += gross - cost
                if new > 1e-12:
                    pos[c] = new
                else:
                    pos.pop(c, None)
                tx.append({"signal_date": signal, "execution_date": d, "stock_code": c, "side": "SELL", "shares": q, "price": p, "gross_notional": gross, "cost": cost, "rank_pos": np.nan})

            buys = []
            total_need = 0.0
            for c in sorted(allc):
                old, new = float(pos.get(c, 0.0)), float(desired.get(c, 0.0))
                if new <= old + 1e-12 or c not in tradable.columns or not bool(tradable.at[d, c]):
                    continue
                p = float(raw.at[d, c])
                q = new - old
                buys.append((c, old, q, p))
                total_need += q * p * (1.0 + cfg.buy_cost)
            scale = min(1.0, cash / total_need) if total_need > 0 else 1.0
            for c, old, q, p in buys:
                q *= scale
                if q <= 1e-12:
                    continue
                gross = q * p
                cost = gross * cfg.buy_cost
                cash -= gross + cost
                pos[c] = old + q
                tx.append({"signal_date": signal, "execution_date": d, "stock_code": c, "side": "BUY", "shares": q, "price": p, "gross_notional": gross, "cost": cost, "rank_pos": np.nan})
        eq.append({"date": d, "equity": equity(d), "cash": cash, "n_positions": len(pos)})

    last = dates[-1]
    for c, sh in list(pos.items()):
        if c not in mark.columns or pd.isna(mark.at[last, c]):
            continue
        p = float(mark.at[last, c])
        gross = sh * p
        cost = gross * cfg.sell_cost
        cash += gross - cost
        tx.append({"signal_date": cfg.end, "execution_date": last, "stock_code": c, "side": "SELL_END", "shares": sh, "price": p, "gross_notional": gross, "cost": cost, "rank_pos": np.nan})
    if eq:
        eq[-1] = {"date": last, "equity": cash, "cash": cash, "n_positions": 0}
    return pd.DataFrame(tx), pd.DataFrame(), pd.DataFrame(eq)


def data_coverage(candidate: dict, frames: dict[str, pd.DataFrame], reference_dates: list[str], test_start: str, end: str):
    expected = set(d for d in reference_dates if test_start <= d <= end)
    ratios = []
    details = {}
    for code in candidate["codes"]:
        df = frames[code]
        dates = set(df.loc[(df["date"] >= test_start) & (df["date"] <= end), "date"].astype(str))
        overlap = len(expected & dates)
        ratio = overlap / len(expected) if expected else 0.0
        ratios.append(ratio)
        details[code] = {"coverage_ratio": ratio, "date_min": min(dates) if dates else None, "date_max": max(dates) if dates else None, "missing_reference_dates": int(len(expected - dates))}
    return min(ratios) if ratios else 0.0, details


def lot_feasibility(events, raw: pd.DataFrame, volume: pd.DataFrame, capital: float, cfg):
    rows = []
    dates = list(raw.index)
    for signal_date, weights, _ in events:
        possible = [d for d in dates if d > signal_date]
        if not possible:
            continue
        execution_date = possible[0]
        gross_budget = float(capital) / (1.0 + cfg.buy_cost)
        invested = 0.0
        achieved = 0
        missing = 0
        for code, w in weights.items():
            if code not in raw.columns or code not in volume.columns:
                missing += 1
                continue
            p = pd.to_numeric(raw.at[execution_date, code], errors="coerce")
            v = pd.to_numeric(volume.at[execution_date, code], errors="coerce")
            if not np.isfinite(p) or p <= 0 or not np.isfinite(v) or v <= 0:
                missing += 1
                continue
            shares = int(np.floor(gross_budget * float(w) / float(p)))
            if shares <= 0:
                continue
            achieved += 1
            invested += shares * float(p)
        buy_cost = invested * cfg.buy_cost
        cash = float(capital) - invested - buy_cost
        rows.append({"signal_date": signal_date, "execution_date": execution_date, "capital_krw": capital, "target_instruments": int(len(weights)), "achieved_instruments": achieved, "missing_or_untradable": missing, "invested_gross": invested, "buy_cost": buy_cost, "residual_cash": cash, "cash_ratio": cash / capital})
    snap = pd.DataFrame(rows)
    if snap.empty:
        return snap, {}
    return snap, {"avg_cash_ratio": float(snap["cash_ratio"].mean()), "max_cash_ratio": float(snap["cash_ratio"].max()), "avg_achieved_instruments": float(snap["achieved_instruments"].mean()), "min_achieved_instruments": int(snap["achieved_instruments"].min()), "missing_or_untradable_total": int(snap["missing_or_untradable"].sum())}


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
    frames, _ = fetch_etf_prices(cfg.test_start, cfg.end, out)
    raw, volume = common_price_frames(frames, cfg.test_start, cfg.end)

    feature_engineer = _register_corrected_mom36(alphakrx, db, cfg)
    print("[panel] build common eligible panel for authoritative reference + market split", flush=True)
    fe = feature_engineer(str(db))
    panel = fe.prepare_ml_data(start_date=cfg.feature_start, end_date=cfg.end, target_horizon=cfg.horizon, min_market_cap=cfg.min_market_cap, use_cache=False, n_workers=1)
    if panel.empty:
        raise RuntimeError("empty feature panel")
    panel = rpt.add_q5_proxy_fields(panel, db)
    panel = rpt.common_universe(panel).sort_values(["date", "stock_code"]).reset_index(drop=True)
    rebal = rpt.global_rebalance_dates(panel, cfg)
    if len(rebal) < 4:
        raise RuntimeError(f"too few rebalance dates: {len(rebal)}")
    print(f"[panel] rows={len(panel):,} names={panel.stock_code.nunique():,} rebalances={len(rebal)}", flush=True)

    sim_cfg = replace(cfg, initial_capital=100_000_000.0)
    ref_sig = pq.signal_frame(panel, rebal, None)
    ref_sm, _, ref_eq = pq.save_fractional(out, "fractional_full_cap_reference", ref_sig, pq.cap_events(panel, rebal, None), db, sim_cfg)
    ref_diffs = pq.validate_reference(ref_sm)
    print(f"[reference] authoritative cap reproduced: {ref_diffs}", flush=True)

    reference_dates = ref_eq["date"].astype(str).tolist()
    perf_rows = []
    lot_rows = []
    recommendations = {}
    candidate_results = {}

    for name, candidate in CANDIDATES.items():
        events, sig = candidate_events(panel, rebal, candidate)
        d = out / name
        d.mkdir(parents=True, exist_ok=True)
        sig.to_csv(d / "signals.csv", index=False, encoding="utf-8-sig")
        tx, ledger, eq = simulate_fractional_etf(events, raw, volume, sim_cfg)
        tx.to_csv(d / "transactions.csv", index=False, encoding="utf-8-sig")
        eq.to_csv(d / "equity_curve.csv", index=False, encoding="utf-8-sig")
        sm = rpt.summarize(eq, tx, ledger, sim_cfg)
        (d / "summary.json").write_text(json.dumps(sm, ensure_ascii=False, indent=2), encoding="utf-8")

        te = pq.tracking_error(eq, ref_eq)
        coverage, coverage_detail = data_coverage(candidate, frames, reference_dates, cfg.test_start, cfg.end)
        cagr_gap = float(sm["cagr"] - ref_sm["cagr"])
        sharpe_gap = float(sm["sharpe"] - ref_sm["sharpe"])
        mdd_gap = float(sm["max_drawdown"] - ref_sm["max_drawdown"])
        checks = {"tracking_error": bool(np.isfinite(te) and te <= FIDELITY_GATES["tracking_error_max"]), "cagr_gap": bool(abs(cagr_gap) <= FIDELITY_GATES["abs_cagr_gap_max"]), "sharpe_gap": bool(abs(sharpe_gap) <= FIDELITY_GATES["abs_sharpe_gap_max"]), "mdd_gap": bool(abs(mdd_gap) <= FIDELITY_GATES["abs_mdd_gap_max"]), "coverage": bool(coverage >= FIDELITY_GATES["coverage_min"])}
        perf_pass = bool(all(checks.values()))
        perf_rows.append({"strategy": name, "instrument_count": len(candidate["codes"]), "codes": "+".join(candidate["codes"]), **sm, "tracking_error": te, "cagr_gap_vs_fractional": cagr_gap, "sharpe_gap_vs_fractional": sharpe_gap, "mdd_gap_vs_fractional": mdd_gap, "coverage_ratio": coverage, **{f"gate_{k}": v for k, v in checks.items()}, "performance_fidelity_pass": perf_pass})
        candidate_results[name] = {"coverage_detail": coverage_detail, "subperiods": pq.subperiods(eq), "performance_checks": checks}

        for capital in CAPITALS:
            snap, lot = lot_feasibility(events, raw, volume, capital, cfg)
            snap.to_csv(d / f"lot_feasibility_{int(capital/1_000_000)}m.csv", index=False, encoding="utf-8-sig")
            lot_checks = {"avg_cash": bool(lot.get("avg_cash_ratio", np.inf) <= FIDELITY_GATES["avg_cash_ratio_max"]), "max_cash": bool(lot.get("max_cash_ratio", np.inf) <= FIDELITY_GATES["max_cash_ratio_max"])}
            lot_pass = bool(all(lot_checks.values()))
            lot_rows.append({"strategy": name, "capital_krw": capital, "instrument_count": len(candidate["codes"]), **lot, **{f"gate_{k}": v for k, v in lot_checks.items()}, "lot_feasibility_pass": lot_pass, "performance_fidelity_pass": perf_pass, "overall_pass": bool(perf_pass and lot_pass), "tracking_error": te})

        print(f"[{name}] CAGR={sm['cagr']:.3%} Sharpe={sm['sharpe']:.3f} MDD={sm['max_drawdown']:.3%} TE={te:.3%} coverage={coverage:.3%} pass={perf_pass}", flush=True)

    perf_df = pd.DataFrame(perf_rows).sort_values(["instrument_count", "tracking_error", "strategy"])
    lot_df = pd.DataFrame(lot_rows).sort_values(["capital_krw", "instrument_count", "tracking_error", "strategy"])
    perf_df.to_csv(out / "performance_comparison.csv", index=False, encoding="utf-8-sig")
    lot_df.to_csv(out / "capital_feasibility.csv", index=False, encoding="utf-8-sig")

    for capital in CAPITALS:
        g = lot_df[(lot_df["capital_krw"] == capital) & (lot_df["overall_pass"])].copy()
        recommendations[str(int(capital))] = None if g.empty else str(g.sort_values(["instrument_count", "tracking_error", "strategy"]).iloc[0]["strategy"])

    manifest = {"methodology_label": "pre-registered personal-quant ETF/index-proxy translation; not alpha optimization", "preregistered_pr": 1, "preregistered_comment_id": PREREG_COMMENT_ID, "finance_datareader_version": FDR_VERSION, "price_source": "FinanceDataReader NAVER daily prices", "distribution_policy": "no dividend/distribution reinvestment, matching current stock benchmark price-return methodology", "config": asdict(cfg), "candidates": CANDIDATES, "capital_grid_krw": CAPITALS, "fidelity_gates": FIDELITY_GATES, "reference_validation_diffs": ref_diffs, "reference_summary": ref_sm, "candidate_details": candidate_results, "recommendations_by_capital": recommendations, "selection_rule": "must pass all fidelity and lot gates; prefer fewer ETF instruments, then lower tracking error", "no_retuning_rule": "do not weaken gates or alter active strategy/universe parameters after observing ETF results"}
    (out / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "recommendations.json").write_text(json.dumps(recommendations, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== ETF proxy performance ===", flush=True)
    print(perf_df.to_string(index=False), flush=True)
    print("\n=== ETF proxy capital feasibility ===", flush=True)
    print(lot_df.to_string(index=False), flush=True)
    print("\n=== Recommendations ===", flush=True)
    print(json.dumps(recommendations, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
