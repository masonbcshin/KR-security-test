#!/usr/bin/env python3
"""Corrected portable tournament runner.

This wrapper keeps the original portable engine intact while fixing two
KR-CORE specification mismatches discovered after the first full audit:

1. mom36m is the Green-et-al style long-horizon momentum characteristic:
   cumulative monthly return from t-36 through t-13 (24 monthly returns),
   NOT the most recent 756-trading-day return.
2. conditional_momentum is restored to the KR-CORE feature list.

The public portable database currently has no deriv_index_daily/VKOSPI table.
AlphaKRX therefore uses its documented neutral fallback vkospi_level_pct=0.5,
so conditional_momentum becomes 0.5 * mom_21d.  This run is therefore a
corrected *portable* KR-CORE test, not an exact reproduction of the frozen
VKOSPI-conditioned KR-CORE v1.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import run_portable_tournament as rpt


# Restore the frozen 11-feature KR-CORE shape.  The portable macro layer will
# supply conditional_momentum via AlphaKRX's neutral 0.5 VKOSPI fallback when
# the public DB has no derivatives table.
rpt.KR_CORE_PORTABLE = [
    "sector_zscore_volatility_63d",
    "sector_zscore_volatility_21d",
    "ma_ratio_5_60",
    "ma_ratio_20_120",
    "mom_36m",
    "conditional_momentum",
    "sector_zscore_mom_21d",
    "sector_zscore_roe",
    "gpa",
    "earnings_growth_yoy",
    "amihud_21d",
]

_ORIGINAL_REGISTER = rpt.register_mom36_and_patch_engine
_ORIGINAL_TRAIN = rpt.train_ml_signals
_DROPPED_FULL: list[str] = []


def _correct_mom36_compute(self, df: pd.DataFrame) -> pd.DataFrame:
    """Add monthly t-36..t-13 cumulative return to every daily row.

    For a signal month M, the characteristic compounds monthly returns for
    M-36 ... M-13 inclusive.  Algebraically (with continuous monthly prices)
    this is P[M-13] / P[M-37] - 1.  We construct a complete calendar-month grid
    and forward-fill month-end prices so a suspension/missing month contributes
    a zero monthly return rather than shortening the horizon.

    Current-month prices never enter the characteristic, so mapping the value
    to every daily row in month M is point-in-time safe.
    """
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

    # Monthly returns lagged 13..36 compound to P[M-13]/P[M-37]-1.
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


def _register_corrected(alphakrx_root: Path, db_path: Path, cfg):
    FeatureEngineer = _ORIGINAL_REGISTER(alphakrx_root, db_path, cfg)
    from ml.features.registry import get_all_groups

    patched = False
    for group_cls in get_all_groups():
        if "mom_36m" in getattr(group_cls, "columns", []):
            group_cls.compute = _correct_mom36_compute
            patched = True
    if not patched:
        raise RuntimeError("could not locate registered mom_36m feature group")
    return FeatureEngineer


def _train_with_portable_compat(df, features, cfg, name, rebal_dates):
    """Only portable_full_ml may shrink to available pinned-engine columns.

    KR-CORE remains strict: all 11 corrected features must exist.
    """
    global _DROPPED_FULL
    if name == "portable_full_ml":
        available = [c for c in features if c in df.columns]
        _DROPPED_FULL = [c for c in features if c not in df.columns]
        if _DROPPED_FULL:
            print(f"[portable_full_ml] unavailable pinned-engine features dropped: {_DROPPED_FULL}", flush=True)
        if len(available) < 10:
            raise RuntimeError(f"portable_full_ml has too few available features: {available}")
        return _ORIGINAL_TRAIN(df, available, cfg, name, rebal_dates)
    return _ORIGINAL_TRAIN(df, features, cfg, name, rebal_dates)


rpt.register_mom36_and_patch_engine = _register_corrected
rpt.train_ml_signals = _train_with_portable_compat
rpt.main()

# Post-run methodology audit.  The panel is deliberately retained by the base
# runner, so we can verify feature availability and whether VKOSPI was neutral.
try:
    out = Path("outputs/tournament")
    panel_path = out / "common_panel.parquet"
    audit = {
        "kr_core_feature_count": len(rpt.KR_CORE_PORTABLE),
        "kr_core_features": rpt.KR_CORE_PORTABLE,
        "mom36_definition": "monthly cumulative return from t-36 through t-13 inclusive (P[t-13]/P[t-37]-1 on a complete month grid)",
        "conditional_momentum_definition": "mom_21d * (1 - vkospi_level_pct)",
        "vkospi_portable_policy": "AlphaKRX neutral fallback 0.5 when deriv_index_daily is unavailable",
        "exact_frozen_v1": False,
        "exact_frozen_v1_blocker": "public portable DB has no historical VKOSPI/deriv_index_daily",
        "dropped_from_portable_full_ml": _DROPPED_FULL,
    }
    if panel_path.exists():
        cols = ["mom_36m", "conditional_momentum", "vkospi_level_pct", "mom_21d"]
        panel = pd.read_parquet(panel_path, columns=[c for c in cols if c in pd.read_parquet(panel_path, engine="pyarrow").columns])
        audit["panel_rows"] = int(len(panel))
        audit["columns_present"] = {c: bool(c in panel.columns) for c in cols}
        if "mom_36m" in panel.columns:
            audit["mom36_non_null_fraction"] = float(panel["mom_36m"].notna().mean())
        if "vkospi_level_pct" in panel.columns:
            v = pd.to_numeric(panel["vkospi_level_pct"], errors="coerce")
            audit["vkospi_neutral_0_5_fraction"] = float(np.isclose(v.fillna(0.5), 0.5).mean())
        if {"conditional_momentum", "mom_21d"}.issubset(panel.columns):
            lhs = pd.to_numeric(panel["conditional_momentum"], errors="coerce")
            rhs = 0.5 * pd.to_numeric(panel["mom_21d"], errors="coerce")
            ok = np.isclose(lhs, rhs, rtol=1e-9, atol=1e-12, equal_nan=True)
            audit["conditional_equals_neutral_half_mom21_fraction"] = float(np.mean(ok))
    (out / "kr_core_spec_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest_path = out / "run_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["kr_core_portable_note"] = (
            "Corrected mom36m and restored conditional_momentum; VKOSPI is neutral-0.5 fallback, "
            "so this is not exact frozen KR-CORE v1."
        )
        manifest["kr_core_features"] = rpt.KR_CORE_PORTABLE
        manifest["kr_core_spec_audit"] = audit
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
except Exception as exc:
    print(f"[kr-core-spec-audit] warning: {exc}", flush=True)
