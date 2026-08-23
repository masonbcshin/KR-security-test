#!/usr/bin/env python3
"""Preregistered defensive-sleeve implementation study for the accepted 60/40 core.

Frozen full-history candidates (PR #1 comment 5383435992):
- zero-yield cash baseline
- KODEX 단기채권PLUS (214980)
- KODEX 단기변동금리부채권액티브 (273140)

Methodology amendments were locked before any candidate result was observed:
- comment 5383468340: reconstruct disclosed distributions
- comment 5383469585: full-history selection uses a conservative after-tax version
- comment 5383492708: add the official 2018 year-end distributions discovered in source audit

The safe ETF is an actual third instrument, whole-share only, reset to 40% only on
accepted 84-trading-day refreshes. Distributions accumulate as cash until the next
scheduled refresh. The conservative tax model applies 15.4% to distributions and
to all positive realised safe-sleeve market-price gains. The latter deliberately
overstates Korean ETF holding-period tax whenever the statutory standard-tax-base
increase is smaller than market gain.

423160/459580 are post-inception operational diagnostics only and cannot rescue or
replace the full-history selection candidates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import FinanceDataReader as fdr

PREREG_COMMENT_ID = 5383435992
DISTRIBUTION_AMENDMENT_COMMENT_ID = 5383468340
AFTER_TAX_SELECTION_COMMENT_ID = 5383469585
HISTORICAL_DISTRIBUTION_CORRECTION_COMMENT_ID = 5383492708
TEST_START = "20180101"
TEST_END = "20260320"
INITIAL_CAPITAL = 100_000_000.0
EQUITY_EXPOSURE = 0.60
SAFE_EXPOSURE = 0.40
BUY_COST = 0.0035
SELL_COST = 0.0055
TAX_RATE = 0.154
BASELINE_TOL = 1e-10
FULL_CANDIDATES = {
    "214980": "KODEX 단기채권PLUS",
    "273140": "KODEX 단기변동금리부채권액티브",
}
DIAGNOSTIC_ONLY = {
    "423160": "KODEX KOFR금리액티브",
    "459580": "KODEX CD금리액티브",
}

# Official disclosed per-share distributions inside the frozen 2018-2026 test.
# Both funds paid an annual year-end distribution in 2018, then official later
# histories show no distribution events during 2019-2024.  Monthly distributions
# began from the Aug-2025 cycle. Dates below are ex-distribution trading dates.
DISTRIBUTIONS = {
    "214980": {
        "20181227": 1785.0,
        "20250813": 244.0,
        "20250912": 236.0,
        "20251014": 232.0,
        "20251113": 238.0,
        "20251212": 236.0,
        "20260114": 251.0,
        "20260212": 258.0,
        "20260312": 239.0,
    },
    "273140": {
        "20181227": 1640.0,
        "20250813": 238.0,
        "20250912": 227.0,
        "20251014": 228.0,
        "20251113": 233.0,
        "20251212": 232.0,
        "20260114": 246.0,
        "20260212": 238.0,
        "20260312": 228.0,
    },
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--accepted-artifact-dir", required=True)
    p.add_argument("--risk-budget-artifact-dir", required=True)
    p.add_argument("--output", default="outputs/etf_safe_sleeve")
    return p.parse_args()


def fetch(code: str, start: str, end: str) -> pd.DataFrame:
    x = fdr.DataReader(
        f"NAVER:{code}",
        pd.Timestamp(start).strftime("%Y-%m-%d"),
        pd.Timestamp(end).strftime("%Y-%m-%d"),
    ).copy().reset_index()
    if x.empty:
        raise RuntimeError(f"empty price series: {code}")
    if "Date" not in x.columns:
        x = x.rename(columns={x.columns[0]: "Date"})
    x["date"] = pd.to_datetime(x["Date"], errors="coerce").dt.strftime("%Y%m%d")
    x["Close"] = pd.to_numeric(x["Close"], errors="coerce")
    x["Volume"] = pd.to_numeric(x["Volume"], errors="coerce")
    return (
        x.dropna(subset=["date", "Close"])
        .sort_values("date")
        .drop_duplicates("date")[["date", "Close", "Volume"]]
    )


def load_accepted(root: Path):
    sig = pd.read_csv(
        root / "cadence_84d" / "signals.csv",
        dtype={"stock_code": str, "date": str},
    )
    raw = None
    vol = None
    for code in ("226490", "229200"):
        x = pd.read_csv(root / f"etf_{code}.csv", dtype={"date": str})
        x = x[(x["date"] >= TEST_START) & (x["date"] <= TEST_END)].copy()
        c = x.set_index("date")[["Close"]].rename(columns={"Close": code})
        v = x.set_index("date")[["Volume"]].rename(columns={"Volume": code})
        raw = c if raw is None else raw.join(c, how="outer")
        vol = v if vol is None else vol.join(v, how="outer")
    return sig, raw.sort_index(), vol.reindex(raw.index).sort_index()


def cash_baseline_reference(root: Path):
    x = pd.read_csv(root / "comparison.csv")
    r = x[np.isclose(pd.to_numeric(x["equity_exposure"]), EQUITY_EXPOSURE)].iloc[0]
    return r.to_dict()


def build_price_panel(eq_raw, eq_vol, safe_code=None):
    raw = eq_raw.copy()
    vol = eq_vol.copy()
    if safe_code:
        s = fetch(safe_code, "2017-12-01", TEST_END)
        raw = raw.join(
            s.set_index("date")[["Close"]].rename(columns={"Close": safe_code}),
            how="left",
        )
        vol = vol.join(
            s.set_index("date")[["Volume"]].rename(columns={"Volume": safe_code}),
            how="left",
        )
    return raw, vol


def simulate(
    signals,
    raw,
    volume,
    safe_code=None,
    start=TEST_START,
    taxable=False,
    include_distributions=False,
):
    raw = raw[(raw.index >= start) & (raw.index <= TEST_END)].copy()
    volume = volume.reindex(raw.index)
    dates = list(raw.index)
    if len(dates) < 2:
        raise RuntimeError("insufficient dates")
    tradable = volume.fillna(0).gt(0) & raw.notna() & raw.gt(0)
    mark = raw.ffill()
    sig = signals[signals["date"] >= start].copy()
    by_exec = {}
    for d, g in sig.groupby("date", sort=True):
        later = [z for z in dates if z > d]
        if not later:
            continue
        weights = {
            str(c): float(v) * EQUITY_EXPOSURE
            for c, v in zip(g["stock_code"], g["target_weight"])
        }
        if safe_code:
            weights[safe_code] = SAFE_EXPOSURE
        by_exec.setdefault(later[0], []).append((str(d), weights))

    cash = INITIAL_CAPITAL
    pos: dict[str, float] = {}
    safe_avg_cost = np.nan
    tx = []
    eq = []
    distributions = []
    cumulative_distribution_gross = 0.0
    cumulative_distribution_tax = 0.0
    cumulative_realized_gain_tax = 0.0

    def equity(d):
        return cash + sum(
            q * float(mark.at[d, c])
            for c, q in pos.items()
            if c in mark.columns and pd.notna(mark.at[d, c])
        )

    def apply_sale_tax(code: str, q: float, p: float) -> float:
        nonlocal cumulative_realized_gain_tax
        if not taxable or code != safe_code or not np.isfinite(safe_avg_cost):
            return 0.0
        gain = max(0.0, (p - float(safe_avg_cost)) * q)
        tax = gain * TAX_RATE
        cumulative_realized_gain_tax += tax
        return tax

    for d in dates:
        # Ex-distribution cash belongs to the position carried into the date;
        # process it before any same-date T+1 rebalance trade.
        if include_distributions and safe_code in DISTRIBUTIONS and d in DISTRIBUTIONS[safe_code]:
            held = float(pos.get(safe_code, 0.0))
            if held > 0:
                per_share = float(DISTRIBUTIONS[safe_code][d])
                gross = held * per_share
                tax = gross * TAX_RATE if taxable else 0.0
                net = gross - tax
                cash += net
                cumulative_distribution_gross += gross
                cumulative_distribution_tax += tax
                distributions.append(
                    {
                        "date": d,
                        "stock_code": safe_code,
                        "shares": held,
                        "distribution_per_share": per_share,
                        "gross_distribution": gross,
                        "tax": tax,
                        "net_distribution": net,
                    }
                )

        for signal, weights in by_exec.get(d, []):
            eq0 = equity(d)
            desired = {}
            for c, w in weights.items():
                if c not in raw.columns or not bool(tradable.at[d, c]):
                    if c in pos:
                        desired[c] = pos[c]
                    continue
                p = float(raw.at[d, c])
                q = eq0 * float(w) / p
                if c == safe_code:
                    q = float(np.floor(q))
                desired[c] = q
            allc = set(pos) | set(desired)

            # Sell first.
            for c in sorted(allc):
                old = float(pos.get(c, 0.0))
                new = float(desired.get(c, 0.0))
                if new >= old - 1e-12 or c not in tradable.columns or not bool(tradable.at[d, c]):
                    continue
                q = old - new
                p = float(raw.at[d, c])
                gross = q * p
                cost = gross * SELL_COST
                gain_tax = apply_sale_tax(c, q, p)
                cash += gross - cost - gain_tax
                if new > 1e-12:
                    pos[c] = new
                else:
                    pos.pop(c, None)
                if c == safe_code and new <= 1e-12:
                    safe_avg_cost = np.nan
                tx.append(
                    {
                        "signal_date": signal,
                        "execution_date": d,
                        "stock_code": c,
                        "side": "SELL",
                        "shares": q,
                        "price": p,
                        "gross_notional": gross,
                        "cost": cost,
                        "realized_gain_tax": gain_tax,
                    }
                )

            # Buy using remaining cash. Equity sleeves keep the accepted
            # fractional-share research convention; the defensive ETF is whole-share.
            buys = []
            need = 0.0
            for c in sorted(allc):
                old = float(pos.get(c, 0.0))
                new = float(desired.get(c, 0.0))
                if new <= old + 1e-12 or c not in tradable.columns or not bool(tradable.at[d, c]):
                    continue
                p = float(raw.at[d, c])
                q = new - old
                buys.append((c, old, q, p))
                need += q * p * (1 + BUY_COST)
            scale = min(1.0, cash / need) if need > 0 else 1.0
            for c, old, q, p in buys:
                q *= scale
                if c == safe_code:
                    q = float(np.floor(q))
                if q <= 1e-12:
                    continue
                gross = q * p
                cost = gross * BUY_COST
                cash -= gross + cost
                pos[c] = old + q
                if c == safe_code:
                    old_basis_value = old * float(safe_avg_cost) if old > 0 and np.isfinite(safe_avg_cost) else 0.0
                    safe_avg_cost = (old_basis_value + q * p) / (old + q)
                tx.append(
                    {
                        "signal_date": signal,
                        "execution_date": d,
                        "stock_code": c,
                        "side": "BUY",
                        "shares": q,
                        "price": p,
                        "gross_notional": gross,
                        "cost": cost,
                        "realized_gain_tax": 0.0,
                    }
                )
        eq.append(
            {
                "date": d,
                "equity": equity(d),
                "cash": cash,
                "n_positions": len(pos),
            }
        )

    # Liquidate at test end for apples-to-apples terminal equity.
    last = dates[-1]
    for c, q in list(pos.items()):
        if c not in mark.columns or pd.isna(mark.at[last, c]):
            continue
        p = float(mark.at[last, c])
        gross = q * p
        cost = gross * SELL_COST
        gain_tax = apply_sale_tax(c, q, p)
        cash += gross - cost - gain_tax
        tx.append(
            {
                "signal_date": TEST_END,
                "execution_date": last,
                "stock_code": c,
                "side": "SELL_END",
                "shares": q,
                "price": p,
                "gross_notional": gross,
                "cost": cost,
                "realized_gain_tax": gain_tax,
            }
        )
    if eq:
        eq[-1] = {"date": last, "equity": cash, "cash": cash, "n_positions": 0}

    txdf = pd.DataFrame(tx)
    distdf = pd.DataFrame(distributions)
    eqdf = pd.DataFrame(eq)
    tax_summary = {
        "taxable": bool(taxable),
        "distribution_gross_krw": float(cumulative_distribution_gross),
        "distribution_tax_krw": float(cumulative_distribution_tax),
        "realized_safe_gain_tax_krw": float(cumulative_realized_gain_tax),
        "total_modeled_tax_krw": float(cumulative_distribution_tax + cumulative_realized_gain_tax),
    }
    return txdf, eqdf, distdf, tax_summary


def metrics(eq, tx, tax_summary=None):
    e = eq.copy()
    e["dt"] = pd.to_datetime(e["date"])
    e = e.sort_values("dt")
    r = e["equity"].pct_change().fillna(0)
    yrs = max((e["dt"].iloc[-1] - e["dt"].iloc[0]).days / 365.25, 1 / 365.25)
    total = e["equity"].iloc[-1] / INITIAL_CAPITAL - 1
    cagr = (1 + total) ** (1 / yrs) - 1
    sd = r.std(ddof=1)
    sharpe = np.sqrt(252) * r.mean() / sd if sd and np.isfinite(sd) else np.nan
    dd = e["equity"] / e["equity"].cummax() - 1
    mdd = float(dd.min())
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    out = {
        "total_return": float(total),
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "max_drawdown": mdd,
        "calmar": float(calmar),
        "transaction_cost_krw": float(tx["cost"].sum()) if len(tx) and "cost" in tx else 0.0,
        "gross_traded_krw": float(tx["gross_notional"].sum()) if len(tx) and "gross_notional" in tx else 0.0,
        "end_equity": float(e["equity"].iloc[-1]),
    }
    if tax_summary:
        out.update(tax_summary)
    return out


def worst_5y(eq):
    v = eq.reset_index(drop=True)["equity"].to_numpy(float)
    w = 1260
    if len(v) <= w:
        return np.nan
    return float(np.min(v[w:] / v[:-w] - 1))


def coverage(code):
    x = fetch(code, "2017-12-01", TEST_END)
    return {
        "date_min": str(x.date.min()),
        "date_max": str(x.date.max()),
        "rows": int(len(x)),
        "zero_volume_rows": int((x.Volume.fillna(0) <= 0).sum()),
        "max_abs_move": float(x.Close.pct_change().abs().max()),
    }


def gate_candidate(m, m0, audit):
    return {
        "gate_mdd": m["max_drawdown"] >= m0["max_drawdown"] - .01,
        "gate_sharpe": m["sharpe"] >= m0["sharpe"] - .03,
        "gate_calmar": m["calmar"] >= m0["calmar"] * .90,
        "gate_cagr": m["cagr"] >= m0["cagr"] - .005,
        "gate_worst5y": m["worst_5y_total_return"] >= m0["worst_5y_total_return"] - .02,
        "gate_integrity": audit["max_abs_move"] < .10,
    }


def main():
    a = parse_args()
    accepted = Path(a.accepted_artifact_dir)
    risk = Path(a.risk_budget_artifact_dir)
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)

    signals, eqraw, eqvol = load_accepted(accepted)
    ref = cash_baseline_reference(risk)
    rows = []
    audits = {}

    # Exact accepted 60/40 zero-yield cash reproduction guard.
    tx0, eq0, dist0, tax0 = simulate(
        signals,
        *build_price_panel(eqraw, eqvol, None),
        safe_code=None,
        taxable=False,
        include_distributions=False,
    )
    m0 = metrics(eq0, tx0, tax0)
    m0["worst_5y_total_return"] = worst_5y(eq0)
    for k in ("cagr", "sharpe", "max_drawdown", "calmar"):
        if abs(float(m0[k]) - float(ref[k])) > BASELINE_TOL:
            raise RuntimeError(f"60/40 baseline reproduction failed {k}: {m0[k]} vs {ref[k]}")
    rows.append(
        {
            "candidate": "cash_zero",
            "label": "40% zero-yield cash",
            "selection_scope": "full_history",
            "tax_mode": "baseline",
            **m0,
            "pass_all": True,
            "selected_eligible": True,
        }
    )
    eq0.to_csv(out / "equity_cash_zero.csv", index=False)
    tx0.to_csv(out / "transactions_cash_zero.csv", index=False)

    # Full-history candidates: compute gross diagnostics and conservative
    # after-tax results. Only after-tax rows are eligible for selection.
    for code, label in FULL_CANDIDATES.items():
        audits[code] = coverage(code)
        if audits[code]["date_min"] > "20180102" or audits[code]["date_max"] < TEST_END:
            raise RuntimeError(f"coverage gate failed {code}: {audits[code]}")
        raw, vol = build_price_panel(eqraw, eqvol, code)
        for taxable, mode in ((False, "gross"), (True, "conservative_after_tax")):
            tx, eq, dist, tax_summary = simulate(
                signals,
                raw,
                vol,
                safe_code=code,
                taxable=taxable,
                include_distributions=True,
            )
            m = metrics(eq, tx, tax_summary)
            m["worst_5y_total_return"] = worst_5y(eq)
            checks = gate_candidate(m, m0, audits[code]) if taxable else {}
            rows.append(
                {
                    "candidate": code,
                    "label": label,
                    "selection_scope": "full_history",
                    "tax_mode": mode,
                    **m,
                    **checks,
                    "pass_all": bool(all(checks.values())) if taxable else False,
                    "selected_eligible": bool(taxable),
                }
            )
            suffix = "after_tax" if taxable else "gross"
            eq.to_csv(out / f"equity_{code}_{suffix}.csv", index=False)
            tx.to_csv(out / f"transactions_{code}_{suffix}.csv", index=False)
            dist.to_csv(out / f"distributions_{code}_{suffix}.csv", index=False)

    # Current KOFR/CD are diagnostic-only because they lack full 2018 history.
    # Their return rows remain explicitly non-selection and price-only.
    for code, label in DIAGNOSTIC_ONLY.items():
        audits[code] = coverage(code)
        start = max(audits[code]["date_min"], TEST_START)
        raw, vol = build_price_panel(eqraw, eqvol, code)
        tx, eq, _, _ = simulate(
            signals,
            raw,
            vol,
            safe_code=code,
            start=start,
            taxable=False,
            include_distributions=False,
        )
        m = metrics(eq, tx) if len(eq) > 1 else {}
        rows.append(
            {
                "candidate": code,
                "label": label,
                "selection_scope": "post_inception_diagnostic_price_only",
                "tax_mode": "not_selection_eligible",
                "diagnostic_start": start,
                **m,
                "pass_all": False,
                "selected_eligible": False,
            }
        )
        if len(eq):
            eq.to_csv(out / f"equity_{code}_diagnostic.csv", index=False)

    df = pd.DataFrame(rows)
    eligible = df[
        (df["selection_scope"] == "full_history")
        & (df["tax_mode"] == "conservative_after_tax")
        & (df["pass_all"] == True)
    ].copy()
    selected = None
    if len(eligible):
        eligible = eligible.sort_values(
            ["max_drawdown", "sharpe", "calmar", "transaction_cost_krw"],
            ascending=[False, False, False, True],
        )
        selected = str(eligible.iloc[0].candidate)
    df["selected_full_history"] = (
        df["candidate"].eq(selected) & df["tax_mode"].eq("conservative_after_tax")
    )
    df.to_csv(out / "comparison.csv", index=False)
    (out / "price_audit.json").write_text(
        json.dumps(audits, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result = {
        "prereg_comment_id": PREREG_COMMENT_ID,
        "distribution_amendment_comment_id": DISTRIBUTION_AMENDMENT_COMMENT_ID,
        "after_tax_selection_comment_id": AFTER_TAX_SELECTION_COMMENT_ID,
        "historical_distribution_correction_comment_id": HISTORICAL_DISTRIBUTION_CORRECTION_COMMENT_ID,
        "selected_full_history": selected,
        "selection_uses": "conservative_after_tax",
        "distribution_accounting": "Official disclosed per-share distributions inside the frozen window: 2018 year-end, no events 2019-2024, monthly Aug-2025 through 2026-03-20; cash retained until scheduled rebalance.",
        "tax_limitation": "15.4% applied to distributions and every positive realised safe-sleeve market-price gain. Actual Korean ETF sale tax is based on min(market gain, standard-tax-base increase), so this can overstate tax.",
        "diagnostic_limitation": "423160/459580 lack full history and are price-only diagnostics; they cannot affect selection.",
        "comparison": df.to_dict("records"),
    }
    (out / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(df.to_string(index=False))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
