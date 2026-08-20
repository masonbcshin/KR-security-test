#!/usr/bin/env python3
"""CI compatibility/audit wrapper for the portable tournament.

Guardrails:
- Only portable_full_ml may shrink to columns actually produced by the pinned
  AlphaKRX engine. KR-CORE remains strict.
- The all-universe cap-weight benchmark uses fractional shares. Applying the
  stock strategies' integer-share constraint to ~1,000 names in a KRW 100m
  account would create artificial cash drag and invalidate the benchmark.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import run_portable_tournament as rpt

_ORIGINAL_TRAIN = rpt.train_ml_signals
_ORIGINAL_SAVE = rpt.save_result
_DROPPED: list[str] = []


def _train_ml_signals_portable(df, features, cfg, name, rebal_dates):
    global _DROPPED
    if name == "portable_full_ml":
        available = [c for c in features if c in df.columns]
        _DROPPED = [c for c in features if c not in df.columns]
        if _DROPPED:
            print(f"[portable_full_ml] unavailable pinned-engine features dropped: {_DROPPED}", flush=True)
        if len(available) < 10:
            raise RuntimeError(
                f"portable_full_ml has too few available features ({len(available)}): {available}"
            )
        return _ORIGINAL_TRAIN(df, available, cfg, name, rebal_dates)
    # KR-CORE and any future named model stay strict.
    return _ORIGINAL_TRAIN(df, features, cfg, name, rebal_dates)


def _simulate_fractional_cap(events, db, cfg):
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
    tx = []
    eq = []

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
                    # A halted existing name cannot be resized on T+1.
                    desired[c] = pos[c]

            allc = set(pos) | set(desired)

            # Sells first.
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

            # Determine all desired incremental buys, then scale proportionally if
            # transaction costs make the pre-cost target unaffordable.
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

    # Close at the final available mark. This is only to make the finite-window
    # after-cost comparison self-contained.
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


def _save_result_audited(root, name, sig, events, db, cfg):
    if name != "universe_cap":
        return _ORIGINAL_SAVE(root, name, sig, events, db, cfg)

    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    sig.to_csv(d / "signals.csv", index=False, encoding="utf-8-sig")
    tx, ledger, eq = _simulate_fractional_cap(events, db, cfg)
    tx.to_csv(d / "transactions.csv", index=False, encoding="utf-8-sig")
    ledger.to_csv(d / "position_ledger.csv", index=False, encoding="utf-8-sig")
    eq.to_csv(d / "equity_curve.csv", index=False, encoding="utf-8-sig")
    sm = rpt.summarize(eq, tx, ledger, cfg)
    (d / "summary.json").write_text(json.dumps(sm, ensure_ascii=False, indent=2), encoding="utf-8")
    return sm


rpt.train_ml_signals = _train_ml_signals_portable
rpt.save_result = _save_result_audited
rpt.main()

# main() has completed successfully here. Add compatibility/methodology audits.
try:
    out = Path("outputs/tournament/portable_feature_compat.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "portable_full_policy": "drop only features absent from pinned engine output; KR-CORE remains strict",
                "dropped_from_portable_full_ml": _DROPPED,
                "benchmark_policy": "fractional-share cap weighting, T+1 execution, same side-specific transaction costs",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
except Exception as exc:
    print(f"[compat-audit] warning: {exc}", flush=True)
