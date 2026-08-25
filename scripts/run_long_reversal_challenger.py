#!/usr/bin/env python3
"""Pre-registered static challenger: LowVol + Trend + Long-Horizon Reversal.

This runner is intentionally narrow.  It changes exactly one signal sign from
corrected `lowvol_trend`: `mom_36m` is ranked as a reversal signal (-1) instead
of momentum (+1).  Every other universe, execution, cost, holding-period and
rank-aggregation rule is inherited unchanged from the portable tournament.

The challenger was pre-registered in PR #1 before its result was observed.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

import run_portable_tournament as rpt


REVERSAL_FEATURES = [
    ("sector_zscore_volatility_63d", -1.0),
    ("sector_zscore_volatility_21d", -1.0),
    ("ma_ratio_5_60", +1.0),
    ("ma_ratio_20_120", +1.0),
    ("sector_zscore_mom_21d", +1.0),
    ("mom_36m", -1.0),  # the only sign change vs corrected lowvol_trend
]


def _correct_mom36_compute(self, df: pd.DataFrame) -> pd.DataFrame:
    """Green-style mom36m: cumulative monthly return t-36 through t-13."""
    price_col = "adj_closing_price" if "adj_closing_price" in df.columns else "closing_price"
    if df.empty:
        df["mom_36m"] = np.nan
        return df

    x = df[["stock_code", "date", price_col]].copy()
    x["_row_id"] = np.arange(len(x), dtype=np.int64)
    x["_dt"] = pd.to_datetime(x["date"], format="%Y%m%d", errors="coerce")
    x["_month"] = x["_dt"].dt.to_period("M")
    x[price_col] = pd.to_numeric(x[price_col], errors="coerce")

    month_end = (
        x.dropna(subset=["_month", price_col])
        .sort_values(["stock_code", "_dt"])
        .groupby(["_month", "stock_code"], as_index=False, sort=True)
        .tail(1)
    )
    if month_end.empty:
        df["mom_36m"] = np.nan
        return df

    wide = month_end.pivot(index="_month", columns="stock_code", values=price_col).sort_index()
    full_months = pd.period_range(wide.index.min(), wide.index.max(), freq="M")
    wide = wide.reindex(full_months).ffill()
    mom = wide.shift(13).div(wide.shift(37)).sub(1.0)
    mom.index.name = "_month"
    long = mom.stack(dropna=False).rename("mom_36m").reset_index()

    merged = x[["_row_id", "stock_code", "_month"]].merge(
        long,
        on=["_month", "stock_code"],
        how="left",
        sort=False,
    ).sort_values("_row_id")
    df["mom_36m"] = pd.to_numeric(merged["mom_36m"], errors="coerce").to_numpy()
    return df


def _register_corrected_mom36(alphakrx_root: Path, db_path: Path, cfg):
    feature_engineer = rpt.register_mom36_and_patch_engine(alphakrx_root, db_path, cfg)
    from ml.features.registry import get_all_groups

    patched = False
    for group_cls in get_all_groups():
        if "mom_36m" in getattr(group_cls, "columns", []):
            group_cls.compute = _correct_mom36_compute
            patched = True
    if not patched:
        raise RuntimeError("could not locate registered mom_36m feature group")
    return feature_engineer


def _simulate_fractional_cap(events, db: Path, cfg):
    """Cost-matched cap benchmark with fractional shares and T+1 execution."""
    codes = sorted(set().union(*[set(w.index) for _, w, _ in events])) if events else []
    px = rpt.load_prices(db, codes, cfg.test_start, cfg.end)
    if px.empty:
        raise RuntimeError("fractional cap benchmark: no price rows")

    raw = px.pivot(index="date", columns="stock_code", values="px").sort_index()
    value = px.pivot(index="date", columns="stock_code", values="value").reindex(raw.index)
    tradable = value.fillna(0).gt(0)
    mark = raw.ffill()
    dates = list(mark.index)

    by_exec = {}
    for signal_date, weights, _ in events:
        possible = [d for d in dates if d > signal_date]
        if possible:
            by_exec.setdefault(possible[0], []).append((signal_date, weights.astype(float)))

    cash = float(cfg.initial_capital)
    pos: dict[str, float] = {}
    tx: list[dict] = []
    eq: list[dict] = []

    def equity(d):
        return cash + sum(
            sh * float(mark.at[d, c])
            for c, sh in pos.items()
            if c in mark.columns and pd.notna(mark.at[d, c])
        )

    for d in dates:
        for signal, weights in by_exec.get(d, []):
            eq0 = equity(d)
            desired: dict[str, float] = {}
            for c, w in weights.items():
                if (
                    w > 0
                    and c in raw.columns
                    and c in tradable.columns
                    and bool(tradable.at[d, c])
                    and pd.notna(raw.at[d, c])
                    and raw.at[d, c] > 0
                ):
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
                tx.append({
                    "signal_date": signal, "execution_date": d, "stock_code": c,
                    "side": "SELL", "shares": q, "price": p,
                    "gross_notional": gross, "cost": cost, "rank_pos": np.nan,
                })

            buys = []
            total_need = 0.0
            for c in sorted(allc):
                old, new = float(pos.get(c, 0.0)), float(desired.get(c, 0.0))
                if new <= old + 1e-12:
                    continue
                p = float(raw.at[d, c])
                q = new - old
                need = q * p * (1.0 + cfg.buy_cost)
                buys.append((c, old, q, p))
                total_need += need
            scale = min(1.0, cash / total_need) if total_need > 0 else 1.0
            for c, old, q, p in buys:
                q *= scale
                if q <= 1e-12:
                    continue
                gross = q * p
                cost = gross * cfg.buy_cost
                cash -= gross + cost
                pos[c] = old + q
                tx.append({
                    "signal_date": signal, "execution_date": d, "stock_code": c,
                    "side": "BUY", "shares": q, "price": p,
                    "gross_notional": gross, "cost": cost, "rank_pos": np.nan,
                })

        eq.append({"date": d, "equity": equity(d), "cash": cash, "n_positions": len(pos)})

    last = dates[-1]
    for c, sh in list(pos.items()):
        if c not in mark.columns or pd.isna(mark.at[last, c]):
            continue
        p = float(mark.at[last, c])
        gross = sh * p
        cost = gross * cfg.sell_cost
        cash += gross - cost
        tx.append({
            "signal_date": cfg.end, "execution_date": last, "stock_code": c,
            "side": "SELL_END", "shares": sh, "price": p,
            "gross_notional": gross, "cost": cost, "rank_pos": np.nan,
        })
    if eq:
        eq[-1] = {"date": last, "equity": cash, "cash": cash, "n_positions": 0}
    return pd.DataFrame(tx), pd.DataFrame(), pd.DataFrame(eq)


def _save_fractional_benchmark(root: Path, sig, events, db: Path, cfg):
    d = root / "universe_cap"
    d.mkdir(parents=True, exist_ok=True)
    sig.to_csv(d / "signals.csv", index=False, encoding="utf-8-sig")
    tx, ledger, eq = _simulate_fractional_cap(events, db, cfg)
    tx.to_csv(d / "transactions.csv", index=False, encoding="utf-8-sig")
    ledger.to_csv(d / "position_ledger.csv", index=False, encoding="utf-8-sig")
    eq.to_csv(d / "equity_curve.csv", index=False, encoding="utf-8-sig")
    sm = rpt.summarize(eq, tx, ledger, cfg)
    (d / "summary.json").write_text(json.dumps(sm, ensure_ascii=False, indent=2), encoding="utf-8")
    return sm


def main():
    a = rpt.parse_args()
    alphakrx = Path(a.alphakrx_root).resolve()
    db = Path(a.db).resolve()
    out = Path(a.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(alphakrx))
    cfg = rpt.Config(a.feature_start, a.test_start, a.end)

    feature_engineer = _register_corrected_mom36(alphakrx, db, cfg)
    print("[panel] build corrected static-feature panel", flush=True)
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

    required = [c for c, _ in REVERSAL_FEATURES]
    missing = [c for c in required if c not in panel.columns]
    if missing:
        raise KeyError(f"long-reversal missing features: {missing}")

    rpt.LOWVOL_TREND = REVERSAL_FEATURES
    sig = rpt.static_signals(panel, cfg, rebal, "lowvol_trend_long_reversal")
    reversal_summary = rpt.save_result(
        out,
        "lowvol_trend_long_reversal",
        sig,
        rpt.events_from_signals(sig, cfg),
        db,
        cfg,
    )

    bench_sig = pd.concat(
        [panel[panel.date.eq(d)][["date", "stock_code", "market_cap"]] for d in rebal],
        ignore_index=True,
    )
    benchmark_summary = _save_fractional_benchmark(
        out,
        bench_sig,
        rpt.cap_events(panel, rebal),
        db,
        cfg,
    )

    comparison = pd.DataFrame([
        {"strategy": "lowvol_trend_long_reversal", **reversal_summary},
        {"strategy": "universe_cap", **benchmark_summary},
    ])
    b = comparison[comparison.strategy.eq("universe_cap")].iloc[0]
    comparison["cagr_alpha_vs_cap"] = comparison.cagr - b.cagr
    comparison["sharpe_delta_vs_cap"] = comparison.sharpe - b.sharpe
    comparison = comparison.sort_values(["sharpe", "calmar"], ascending=False, na_position="last")
    comparison.to_csv(out / "comparison.csv", index=False, encoding="utf-8-sig")

    subperiods = {}
    for name in comparison.strategy:
        eqf = out / name / "equity_curve.csv"
        subperiods[name] = {
            "2018_2021": rpt.subperiod_metric(eqf, "20180101", "20211231"),
            "2022_2026": rpt.subperiod_metric(eqf, "20220101", "20261231"),
        }

    manifest = {
        "config": asdict(cfg),
        "strategy": "lowvol_trend_long_reversal",
        "methodology_label": "pre-registered retrospective/pseudo-OOS challenger; not untouched forward OOS",
        "preregistered_pr": 1,
        "preregistered_comment_id": 5352538282,
        "feature_signs": REVERSAL_FEATURES,
        "single_change_vs_corrected_lowvol_trend": "mom_36m sign +1 -> -1",
        "mom36_definition": "monthly cumulative return t-36 through t-13 inclusive",
        "benchmark_policy": "fractional-share cap weighting, T+1 execution, same side-specific costs",
        "subperiods": subperiods,
        "winner_rule": "after-cost Sharpe first, then Calmar/MDD, CAGR alpha, subperiod stability, turnover/cost",
    }
    (out / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(comparison.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
