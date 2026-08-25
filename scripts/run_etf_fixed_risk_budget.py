#!/usr/bin/env python3
"""Frozen fixed-equity-risk-budget study for the accepted 84d two-ETF baseline.

Pre-registered in KR-security-test PR #1 comment 5376827268 before result inspection.
Only the equity risk budget changes. Accepted ETF weights, signal dates, T+1 execution,
and costs stay fixed. Residual capital earns 0% and is reset only at existing 84d refreshes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

PREREG_COMMENT_ID = 5376827268
EXPOSURES = (1.0, 0.8, 0.7, 0.6, 0.5)
BUY_COST = 0.0035
SELL_COST = 0.0055
INITIAL_CAPITAL = 100_000_000.0
TEST_START = "20180101"
TEST_END = "20260320"
BASELINE_TOL = 1e-10
BOOTSTRAP_PATHS = 20_000
BOOTSTRAP_BLOCK = 21
BOOTSTRAP_SEED = 20260822


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--accepted-artifact-dir", required=True)
    p.add_argument("--output", default="outputs/etf_fixed_risk_budget")
    return p.parse_args()


def load_inputs(root: Path):
    sig = pd.read_csv(root / "cadence_84d" / "signals.csv", dtype={"stock_code": str})
    sig["date"] = sig["date"].astype(str)
    raw = None
    volume = None
    for code in ("226490", "229200"):
        df = pd.read_csv(root / f"etf_{code}.csv", dtype={"date": str})
        x = df[(df["date"] >= TEST_START) & (df["date"] <= TEST_END)].set_index("date")
        c = x[["Close"]].rename(columns={"Close": code})
        v = x[["Volume"]].rename(columns={"Volume": code})
        raw = c if raw is None else raw.join(c, how="outer")
        volume = v if volume is None else volume.join(v, how="outer")
    return sig, raw.sort_index(), volume.reindex(raw.index).sort_index()


def events(signals: pd.DataFrame, exposure: float):
    out = []
    for d, g in signals.groupby("date", sort=True):
        w = pd.Series(
            {c: float(v) * exposure for c, v in zip(g["stock_code"], g["target_weight"])},
            dtype=float,
        )
        out.append((str(d), w))
    return out


def simulate(signals: pd.DataFrame, raw: pd.DataFrame, volume: pd.DataFrame, exposure: float):
    tradable = volume.fillna(0).gt(0) & raw.notna() & raw.gt(0)
    mark = raw.ffill()
    dates = list(mark.index)
    by_exec = {}
    for signal_date, weights in events(signals, exposure):
        later = [d for d in dates if d > signal_date]
        if later:
            by_exec.setdefault(later[0], []).append((signal_date, weights))

    cash = INITIAL_CAPITAL
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
            desired = {}
            for c, w in weights.items():
                if c in raw.columns and bool(tradable.at[d, c]) and pd.notna(raw.at[d, c]) and raw.at[d, c] > 0:
                    desired[c] = eq0 * float(w) / float(raw.at[d, c])
                elif c in pos:
                    desired[c] = pos[c]
            allc = set(pos) | set(desired)

            for c in sorted(allc):
                old = float(pos.get(c, 0.0)); new = float(desired.get(c, 0.0))
                if new >= old - 1e-12:
                    continue
                if c not in tradable.columns or not bool(tradable.at[d, c]):
                    continue
                q = old - new; p = float(raw.at[d, c]); gross = q * p; cost = gross * SELL_COST
                cash += gross - cost
                if new > 1e-12:
                    pos[c] = new
                else:
                    pos.pop(c, None)
                tx.append({"signal_date": signal, "execution_date": d, "stock_code": c, "side": "SELL", "shares": q, "price": p, "gross_notional": gross, "cost": cost})

            buys = []
            total_need = 0.0
            for c in sorted(allc):
                old = float(pos.get(c, 0.0)); new = float(desired.get(c, 0.0))
                if new <= old + 1e-12 or c not in tradable.columns or not bool(tradable.at[d, c]):
                    continue
                p = float(raw.at[d, c]); q = new - old
                buys.append((c, old, q, p)); total_need += q * p * (1.0 + BUY_COST)
            scale = min(1.0, cash / total_need) if total_need > 0 else 1.0
            for c, old, q, p in buys:
                q *= scale
                if q <= 1e-12:
                    continue
                gross = q * p; cost = gross * BUY_COST
                cash -= gross + cost; pos[c] = old + q
                tx.append({"signal_date": signal, "execution_date": d, "stock_code": c, "side": "BUY", "shares": q, "price": p, "gross_notional": gross, "cost": cost})
        eq.append({"date": d, "equity": equity(d), "cash": cash, "n_positions": len(pos)})

    last = dates[-1]
    for c, sh in list(pos.items()):
        if c not in mark.columns or pd.isna(mark.at[last, c]):
            continue
        p = float(mark.at[last, c]); gross = sh * p; cost = gross * SELL_COST
        cash += gross - cost
        tx.append({"signal_date": TEST_END, "execution_date": last, "stock_code": c, "side": "SELL_END", "shares": sh, "price": p, "gross_notional": gross, "cost": cost})
    if eq:
        eq[-1] = {"date": last, "equity": cash, "cash": cash, "n_positions": 0}
    return pd.DataFrame(tx), pd.DataFrame(eq)


def metrics(eq: pd.DataFrame, tx: pd.DataFrame):
    e = eq.copy(); e["dt"] = pd.to_datetime(e["date"]); e = e.sort_values("dt")
    e["ret"] = e["equity"].pct_change().fillna(0)
    years = max((e["dt"].iloc[-1] - e["dt"].iloc[0]).days / 365.25, 1 / 365.25)
    total = e["equity"].iloc[-1] / INITIAL_CAPITAL - 1
    cagr = (1 + total) ** (1 / years) - 1
    sd = e["ret"].std(ddof=1)
    sharpe = np.sqrt(252) * e["ret"].mean() / sd if sd and np.isfinite(sd) else np.nan
    dd = e["equity"] / e["equity"].cummax() - 1
    mdd = float(dd.min())
    return {
        "total_return": float(total), "cagr": float(cagr), "sharpe": float(sharpe),
        "max_drawdown": mdd, "calmar": float(cagr / abs(mdd)) if mdd < 0 else np.nan,
        "transaction_cost_krw": float(tx["cost"].sum()) if not tx.empty else 0.0,
        "gross_traded_krw": float(tx["gross_notional"].sum()) if not tx.empty else 0.0,
        "end_equity": float(e["equity"].iloc[-1]),
    }


def period_metrics(eq: pd.DataFrame, start: str, end: str):
    e = eq[(eq["date"] >= start) & (eq["date"] <= end)].copy()
    r = e["equity"].pct_change().fillna(0); sd = r.std(ddof=1)
    return {
        "return": float(e["equity"].iloc[-1] / e["equity"].iloc[0] - 1),
        "sharpe": float(np.sqrt(252) * r.mean() / sd) if sd and np.isfinite(sd) else np.nan,
        "mdd": float((e["equity"] / e["equity"].cummax() - 1).min()),
    }


def longest_underwater(eq: pd.DataFrame):
    e = eq.copy().reset_index(drop=True); e["dt"] = pd.to_datetime(e["date"])
    under = (e["equity"] < e["equity"].cummax() * (1 - 1e-12)).to_numpy()
    longest = 0; best = None; start = None
    for i, u in enumerate(under):
        if u and start is None:
            start = i
        if not u and start is not None:
            if i - start > longest:
                longest = i - start; best = (start, i)
            start = None
    if start is not None and len(e) - start > longest:
        longest = len(e) - start; best = (start, len(e) - 1)
    if best is None:
        return {"longest_underwater_trading_days": 0, "longest_underwater_calendar_days": 0}
    s, t = best
    return {
        "longest_underwater_trading_days": int(longest),
        "longest_underwater_calendar_days": int((e.loc[t, "dt"] - e.loc[s, "dt"]).days),
    }


def rolling(eq: pd.DataFrame, window: int):
    v = eq["equity"].to_numpy(float)
    ann = (v[window:] / v[:-window]) ** (252 / window) - 1
    return {
        "positive_rate": float((ann > 0).mean()), "worst": float(np.min(ann)),
        "p05": float(np.quantile(ann, .05)), "median": float(np.quantile(ann, .50)),
        "p95": float(np.quantile(ann, .95)),
    }


def bootstrap(eq: pd.DataFrame):
    r = eq["equity"].pct_change().fillna(0).to_numpy(float)[1:]
    n = len(r); starts = np.arange(0, n - BOOTSTRAP_BLOCK + 1); rng = np.random.default_rng(BOOTSTRAP_SEED)
    cagrs = np.empty(BOOTSTRAP_PATHS); mdds = np.empty(BOOTSTRAP_PATHS); years = n / 252
    for i in range(BOOTSTRAP_PATHS):
        pieces = []; remain = n
        while remain > 0:
            s = int(rng.choice(starts)); take = min(BOOTSTRAP_BLOCK, remain)
            pieces.append(r[s:s + take]); remain -= take
        path = np.concatenate(pieces); curve = np.cumprod(1 + path)
        cagrs[i] = curve[-1] ** (1 / years) - 1
        peak = np.maximum.accumulate(curve); mdds[i] = np.min(curve / peak - 1)
    return {
        "paths": BOOTSTRAP_PATHS, "block": BOOTSTRAP_BLOCK, "seed": BOOTSTRAP_SEED,
        "cagr_p05": float(np.quantile(cagrs, .05)), "cagr_p25": float(np.quantile(cagrs, .25)),
        "cagr_median": float(np.quantile(cagrs, .50)), "cagr_p75": float(np.quantile(cagrs, .75)),
        "cagr_p95": float(np.quantile(cagrs, .95)), "prob_ending_loss": float((cagrs < 0).mean()),
        "mdd_p05": float(np.quantile(mdds, .05)), "mdd_median": float(np.quantile(mdds, .50)),
        "prob_mdd_le_30": float((mdds <= -.30).mean()), "prob_mdd_le_40": float((mdds <= -.40).mean()),
        "prob_mdd_le_50": float((mdds <= -.50).mean()),
    }


def main():
    a = parse_args(); src = Path(a.accepted_artifact_dir).resolve(); out = Path(a.output).resolve(); out.mkdir(parents=True, exist_ok=True)
    signals, raw, volume = load_inputs(src)
    accepted = json.loads((src / "cadence_84d" / "summary.json").read_text(encoding="utf-8"))
    rows = []; eqs = {}
    for exposure in EXPOSURES:
        tx, eq = simulate(signals, raw, volume, exposure); eqs[exposure] = eq
        sm = metrics(eq, tx); pre = period_metrics(eq, "20180101", "20241231")
        p1 = period_metrics(eq, "20180101", "20211231"); p2 = period_metrics(eq, "20220101", "20241231"); p3 = period_metrics(eq, "20250101", "20260320")
        uw = longest_underwater(eq)
        rows.append({"equity_exposure": exposure, "cash_target": 1 - exposure, **sm,
                     "pre2025_return": pre["return"], "pre2025_sharpe": pre["sharpe"],
                     "sp_2018_2021_sharpe": p1["sharpe"], "sp_2022_2024_sharpe": p2["sharpe"], "sp_2025_2026_sharpe": p3["sharpe"], **uw})
        eq.to_csv(out / f"equity_exposure_{int(exposure*100)}.csv", index=False)
        tx.to_csv(out / f"transactions_exposure_{int(exposure*100)}.csv", index=False)
    df = pd.DataFrame(rows)
    base = df[df["equity_exposure"].eq(1.0)].iloc[0]
    for key in ("cagr", "sharpe", "max_drawdown", "calmar"):
        if abs(float(base[key]) - float(accepted[key])) > BASELINE_TOL:
            raise RuntimeError(f"accepted baseline reproduction failed for {key}: {base[key]} vs {accepted[key]}")

    gates = []
    for _, r in df.iterrows():
        checks = {
            "gate_mdd_le_30": abs(r["max_drawdown"]) <= .30 + 1e-12,
            "gate_sharpe_floor": r["sharpe"] >= base["sharpe"] - .03 - 1e-12,
            "gate_calmar_floor": r["calmar"] >= base["calmar"] - 1e-12,
            "gate_cagr_ge_6": r["cagr"] >= .06 - 1e-12,
            "gate_pre2025_positive": r["pre2025_return"] > 0 and r["pre2025_sharpe"] >= 0,
            "gate_subperiod_stability": min(r["sp_2018_2021_sharpe"] - base["sp_2018_2021_sharpe"], r["sp_2022_2024_sharpe"] - base["sp_2022_2024_sharpe"], r["sp_2025_2026_sharpe"] - base["sp_2025_2026_sharpe"]) >= -.15 - 1e-12,
            "gate_underwater_not_longer": r["longest_underwater_trading_days"] <= base["longest_underwater_trading_days"],
        }
        gates.append({"equity_exposure": r["equity_exposure"], **checks, "all_pass": bool(all(checks.values()))})
    g = pd.DataFrame(gates); df = df.merge(g, on="equity_exposure", how="left")
    passers = df[df["all_pass"]].copy()
    selected = None if passers.empty else float(passers.sort_values(["sharpe", "calmar", "cagr"], ascending=[False, False, False]).iloc[0]["equity_exposure"])

    df.to_csv(out / "comparison.csv", index=False)
    diag = None
    if selected is not None:
        e = eqs[selected]
        diag = {"selected_exposure": selected, "rolling": {str(w): rolling(e, w) for w in (252, 756, 1260)}, "bootstrap": bootstrap(e)}
        (out / "postselection_diagnostic.json").write_text(json.dumps(diag, indent=2), encoding="utf-8")
    result = {"preregistered_comment_id": PREREG_COMMENT_ID, "candidates": EXPOSURES,
              "selection": selected, "decision": "PASS_FIXED_RISK_BUDGET" if selected is not None else "NO_CANDIDATE_PASSES",
              "note": "bootstrap/rolling diagnostics are post-selection diagnostics and are not used to choose exposure", "postselection_diagnostic": diag}
    (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(df.to_string(index=False)); print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
