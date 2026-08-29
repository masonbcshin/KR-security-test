from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

BASE = {
    "069500.KS": 0.30,
    "143850.KS": 0.30,
    "148070.KS": 0.15,
    "GOLD": 0.15,
    "153130.KS": 0.10,
}
CASH = "153130.KS"
FUT_GOLD = "132030.KS"
SPOT_GOLD = "411060.KS"
SYN_GOLD = "SYN_GOLD_KRW"
KOREAN_FIXED = ["069500.KS", "143850.KS", "148070.KS", CASH]
SMA = 200
COSTS = [10.0, 25.0, 50.0]
EXECUTIONS = ["next_open", "next_close"]
SEED = 20260829
OUT = Path("gold_instrument_ablation/out")


def download_one(symbol: str, start: str = "2010-01-01") -> pd.DataFrame:
    d = yf.download(
        symbol,
        start=start,
        auto_adjust=False,
        actions=True,
        progress=False,
        threads=False,
        timeout=30,
    )
    if isinstance(d.columns, pd.MultiIndex):
        if symbol in d.columns.get_level_values(-1):
            d = d.xs(symbol, level=-1, axis=1)
        elif symbol in d.columns.get_level_values(0):
            d = d.xs(symbol, level=0, axis=1)
    need = {"Open", "Close", "Adj Close"}
    if d.empty or not need.issubset(d.columns):
        raise RuntimeError(f"missing Yahoo data for {symbol}: {list(d.columns)}")
    d = d[["Open", "Close", "Adj Close"]].copy()
    d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
    for c in d.columns:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna()
    d["Adj Open"] = d["Open"] * d["Adj Close"] / d["Close"].replace(0, np.nan)
    d = d.dropna()
    if len(d) < 250 or (d[["Close", "Adj Close", "Adj Open"]] <= 0).any().any():
        raise RuntimeError(f"invalid data for {symbol}: rows={len(d)}")
    return d


def month_ends(idx: pd.DatetimeIndex) -> list[pd.Timestamp]:
    s = pd.Series(idx, index=idx)
    return [pd.Timestamp(x) for x in s.groupby(idx.to_period("M")).last().tolist()]


def next_day(idx: pd.DatetimeIndex, d: pd.Timestamp) -> pd.Timestamp | None:
    i = idx.searchsorted(d, side="right")
    return pd.Timestamp(idx[i]) if i < len(idx) else None


def assemble_actual(data: dict[str, pd.DataFrame]):
    syms = KOREAN_FIXED + [FUT_GOLD, SPOT_GOLD]
    common = None
    for s in syms:
        common = data[s].index if common is None else common.intersection(data[s].index)
    common = pd.DatetimeIndex(common).sort_values()
    raw = pd.DataFrame({s: data[s].loc[common, "Close"] for s in syms})
    adj = pd.DataFrame({s: data[s].loc[common, "Adj Close"] for s in syms})
    aopen = pd.DataFrame({s: data[s].loc[common, "Adj Open"] for s in syms})
    return raw, adj, aopen


def make_synthetic(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    gld, fx = data["GLD"], data["KRW=X"]
    idx = gld.index.intersection(fx.index).sort_values()
    out = pd.DataFrame(index=idx)
    out["Close"] = gld.loc[idx, "Close"] * fx.loc[idx, "Close"]
    out["Adj Close"] = gld.loc[idx, "Adj Close"] * fx.loc[idx, "Adj Close"]
    out["Adj Open"] = gld.loc[idx, "Adj Open"] * fx.loc[idx, "Adj Open"]
    return out.dropna()


def assemble_long(data: dict[str, pd.DataFrame], syn: pd.DataFrame):
    sources: dict[str, pd.DataFrame] = {s: data[s] for s in KOREAN_FIXED + [FUT_GOLD]}
    sources[SYN_GOLD] = syn
    common = None
    for d in sources.values():
        common = d.index if common is None else common.intersection(d.index)
    common = pd.DatetimeIndex(common).sort_values()
    raw = pd.DataFrame({s: d.loc[common, "Close"] for s, d in sources.items()})
    adj = pd.DataFrame({s: d.loc[common, "Adj Close"] for s, d in sources.items()})
    aopen = pd.DataFrame({s: d.loc[common, "Adj Open"] for s, d in sources.items()})
    return raw, adj, aopen


def target(raw: pd.DataFrame, d: pd.Timestamp, gold: str) -> pd.Series:
    universe = list(raw.columns)
    w = pd.Series(0.0, index=universe)
    risky = ["069500.KS", "143850.KS", "148070.KS", gold]
    base = {
        "069500.KS": BASE["069500.KS"],
        "143850.KS": BASE["143850.KS"],
        "148070.KS": BASE["148070.KS"],
        gold: BASE["GOLD"],
    }
    w[CASH] = BASE[CASH]
    for s in risky:
        h = raw.loc[:d, s].dropna()
        if len(h) < SMA:
            raise ValueError(f"short SMA history {s} at {d.date()}: {len(h)}")
        sma = float(h.tail(SMA).mean())
        if float(h.iloc[-1]) >= sma:
            w[s] = base[s]
        else:
            w[CASH] += base[s]
    if abs(float(w.sum()) - 1.0) > 1e-9:
        raise ValueError(w.to_dict())
    return w


def periods(raw: pd.DataFrame, adj: pd.DataFrame, aopen: pd.DataFrame, execution: str, gold: str):
    idx = raw.index
    ends = [d for d in month_ends(idx) if idx.get_loc(d) >= SMA - 1]
    rebs = [(d, next_day(idx, d)) for d in ends]
    rebs = [(s, e) for s, e in rebs if e is not None]
    px = aopen if execution == "next_open" else adj
    rows, tgts = [], []
    for i in range(len(rebs) - 1):
        sd, rd = rebs[i]
        _, nrd = rebs[i + 1]
        ar = px.loc[nrd] / px.loc[rd] - 1
        rows.append({"date": rd, **{f"r_{s}": float(ar[s]) for s in raw.columns}})
        tgts.append(pd.Series(target(raw, sd, gold), name=rd))
    if not rows:
        raise RuntimeError("no rebalance periods")
    p = pd.DataFrame(rows).set_index("date")
    t = pd.DataFrame(tgts).reindex(p.index).fillna(0.0)
    return p, t


def simulate(p: pd.DataFrame, t: pd.DataFrame, bp: float) -> pd.DataFrame:
    universe = list(t.columns)
    cur = pd.Series(0.0, index=universe)
    cur[CASH] = 1.0
    out = []
    for d, row in p.iterrows():
        w = t.loc[d, universe].astype(float)
        turnover = float((w - cur).abs().sum())
        cost = turnover * bp / 10000.0
        ar = pd.Series({s: float(row[f"r_{s}"]) for s in universe})
        gross = float((w * ar).sum())
        net = (1.0 - cost) * (1.0 + gross) - 1.0
        cur = w * (1.0 + ar) / (1.0 + gross)
        out.append({
            "date": d,
            "return": net,
            "rf": float(ar[CASH]),
            "turnover": turnover,
            "cost": cost,
        })
    return pd.DataFrame(out).set_index("date")


def stats(x: pd.DataFrame) -> dict:
    r, rf = x["return"], x["rf"]
    n = len(r)
    eq = (1 + r).cumprod()
    cagr = float(eq.iloc[-1] ** (12 / n) - 1)
    ex = r - rf
    sd = float(ex.std(ddof=1) * math.sqrt(12))
    sharpe = float(ex.mean() * 12 / sd) if sd else np.nan
    dd = eq / eq.cummax() - 1
    mdd = float(dd.min())
    roll12 = (1 + r).rolling(12).apply(np.prod, raw=True) - 1
    return {
        "months": n,
        "start": str(x.index.min().date()),
        "end": str(x.index.max().date()),
        "cagr": cagr,
        "sharpe": sharpe,
        "mdd": mdd,
        "calmar": cagr / abs(mdd) if mdd < 0 else np.nan,
        "worst_12m": float(roll12.min()) if roll12.notna().any() else np.nan,
        "annual_turnover": float(x.turnover.sum() / (n / 12)),
    }


def bootstrap_prob(spot: pd.DataFrame, fut: pd.DataFrame, block: int = 6, nboot: int = 4000) -> float:
    idx = spot.index.intersection(fut.index)
    sr = spot.loc[idx, "return"].to_numpy()
    fr = fut.loc[idx, "return"].to_numpy()
    rf = spot.loc[idx, "rf"].to_numpy()
    n = len(idx)
    rng = np.random.default_rng(SEED)
    wins = 0

    def sh(r: np.ndarray, take: np.ndarray) -> float:
        e = r[take] - rf[take]
        sd = e.std(ddof=1)
        return float(e.mean() / sd * math.sqrt(12)) if sd else np.nan

    for _ in range(nboot):
        take: list[int] = []
        while len(take) < n:
            st = int(rng.integers(0, n))
            take.extend((st + j) % n for j in range(block))
        arr = np.array(take[:n])
        wins += bool(sh(sr, arr) > sh(fr, arr))
    return wins / nboot


def monthly_returns(series: pd.Series) -> pd.Series:
    s = series.dropna().sort_index()
    last = s.groupby(s.index.to_period("M")).last()
    last.index = last.index.to_timestamp("M")
    return last.pct_change().dropna()


def proxy_validation(data: dict[str, pd.DataFrame], syn: pd.DataFrame) -> dict:
    a = monthly_returns(data[SPOT_GOLD]["Adj Close"])
    b = monthly_returns(syn["Adj Close"])
    idx = a.index.intersection(b.index)
    a, b = a.loc[idx], b.loc[idx]
    corr = float(a.corr(b))
    te = float((a - b).std(ddof=1) * math.sqrt(12))
    return {
        "months": len(idx),
        "start": str(idx.min().date()),
        "end": str(idx.max().date()),
        "monthly_return_correlation": corr,
        "annualized_tracking_error": te,
        "corr_ge_095": corr >= 0.95,
        "tracking_error_le_006": te <= 0.06,
    }


def run_pair(raw, adj, aopen, gold_a: str, gold_b: str, stage: str):
    metrics = []
    sims = {}
    labels = {gold_a: "G_FUTURES_H", gold_b: "G_SPOT_KRX" if gold_b == SPOT_GOLD else "G_SYN_SPOT_KRW"}
    for exe in EXECUTIONS:
        for gold in (gold_a, gold_b):
            p, t = periods(raw, adj, aopen, exe, gold)
            for cost in COSTS:
                sim = simulate(p, t, cost)
                sims[(labels[gold], cost, exe)] = sim
                m = stats(sim)
                m.update(stage=stage, candidate=labels[gold], gold_symbol=gold, cost_bp=cost, execution=exe)
                metrics.append(m)
    return pd.DataFrame(metrics), sims


def pick(df: pd.DataFrame, candidate: str, cost=10.0, exe="next_open") -> pd.Series:
    z = df[(df.candidate == candidate) & (df.cost_bp == cost) & (df.execution == exe)]
    if len(z) != 1:
        raise RuntimeError(f"metric row mismatch {candidate} {cost} {exe}: {len(z)}")
    return z.iloc[0]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    symbols = KOREAN_FIXED + [FUT_GOLD, SPOT_GOLD, "GLD", "KRW=X"]
    data = {s: download_one(s, "2004-01-01" if s in ("GLD", "KRW=X") else "2010-01-01") for s in symbols}
    syn = make_synthetic(data)

    raw_a, adj_a, open_a = assemble_actual(data)
    actual_df, actual_sims = run_pair(raw_a, adj_a, open_a, FUT_GOLD, SPOT_GOLD, "ACTUAL_OVERLAP")
    actual_df.to_csv(OUT / "actual_metrics.csv", index=False)

    proxy = proxy_validation(data, syn)
    (OUT / "proxy_validation.json").write_text(json.dumps(proxy, indent=2), encoding="utf-8")

    raw_l, adj_l, open_l = assemble_long(data, syn)
    long_df, long_sims = run_pair(raw_l, adj_l, open_l, FUT_GOLD, SYN_GOLD, "LONG_SYNTHETIC")
    long_df.to_csv(OUT / "long_metrics.csv", index=False)

    af = pick(actual_df, "G_FUTURES_H")
    asp = pick(actual_df, "G_SPOT_KRX")
    af25 = pick(actual_df, "G_FUTURES_H", 25.0)
    asp25 = pick(actual_df, "G_SPOT_KRX", 25.0)
    afc = pick(actual_df, "G_FUTURES_H", 10.0, "next_close")
    aspc = pick(actual_df, "G_SPOT_KRX", 10.0, "next_close")
    prob = bootstrap_prob(actual_sims[("G_SPOT_KRX", 10.0, "next_open")], actual_sims[("G_FUTURES_H", 10.0, "next_open")])

    actual_checks = {
        "sharpe_spot_gt_futures": float(asp.sharpe) > float(af.sharpe),
        "calmar_spot_ge_futures": float(asp.calmar) >= float(af.calmar),
        "mdd_spot_no_more_than_10pct_worse": abs(float(asp.mdd)) <= 1.10 * abs(float(af.mdd)),
        "cost25_sharpe_spot_gt_futures": float(asp25.sharpe) > float(af25.sharpe),
        "next_close_sharpe_spot_gt_futures": float(aspc.sharpe) > float(afc.sharpe),
        "bootstrap_ge_70pct": prob >= 0.70,
    }

    lf = pick(long_df, "G_FUTURES_H")
    lsp = pick(long_df, "G_SYN_SPOT_KRW")
    lf25 = pick(long_df, "G_FUTURES_H", 25.0)
    lsp25 = pick(long_df, "G_SYN_SPOT_KRW", 25.0)
    lfc = pick(long_df, "G_FUTURES_H", 10.0, "next_close")
    lspc = pick(long_df, "G_SYN_SPOT_KRW", 10.0, "next_close")
    long_checks = {
        "sharpe_syn_spot_gt_futures": float(lsp.sharpe) > float(lf.sharpe),
        "calmar_syn_spot_ge_futures": float(lsp.calmar) >= float(lf.calmar),
        "mdd_syn_spot_no_more_than_10pct_worse": abs(float(lsp.mdd)) <= 1.10 * abs(float(lf.mdd)),
        "cost25_sharpe_syn_spot_gt_futures": float(lsp25.sharpe) > float(lf25.sharpe),
        "next_close_sharpe_syn_spot_gt_futures": float(lspc.sharpe) > float(lfc.sharpe),
    }
    proxy_ok = bool(proxy["corr_ge_095"] and proxy["tracking_error_le_006"])
    actual_perf_ok = all(v for k, v in actual_checks.items() if k != "bootstrap_ge_70pct")

    if all(actual_checks.values()) and proxy_ok and all(long_checks.values()):
        decision = "SPOT_REPLACEMENT_EVIDENCE_STRONG"
    elif actual_perf_ok and not actual_checks["bootstrap_ge_70pct"]:
        decision = "SPOT_FORWARD_CANDIDATE_ONLY"
    else:
        decision = "KEEP_FUTURES_NO_REPLACEMENT_EVIDENCE"

    verdict = {
        "decision": decision,
        "actual_checks": actual_checks,
        "bootstrap_prob_sharpe_spot_gt_futures": prob,
        "proxy_validation": proxy,
        "long_checks": long_checks,
        "actual_primary": {
            "G_FUTURES_H": {k: float(af[k]) for k in ("cagr", "sharpe", "mdd", "calmar", "annual_turnover")},
            "G_SPOT_KRX": {k: float(asp[k]) for k in ("cagr", "sharpe", "mdd", "calmar", "annual_turnover")},
        },
        "long_primary": {
            "G_FUTURES_H": {k: float(lf[k]) for k in ("cagr", "sharpe", "mdd", "calmar", "annual_turnover")},
            "G_SYN_SPOT_KRW": {k: float(lsp[k]) for k in ("cagr", "sharpe", "mdd", "calmar", "annual_turnover")},
        },
    }
    (OUT / "verdict.json").write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")

    manifest = {
        "provider": "Yahoo Finance via yfinance",
        "actual_common_start": str(raw_a.index.min().date()),
        "actual_common_end": str(raw_a.index.max().date()),
        "actual_common_rows": len(raw_a),
        "long_common_start": str(raw_l.index.min().date()),
        "long_common_end": str(raw_l.index.max().date()),
        "long_common_rows": len(raw_l),
        "sma_days": SMA,
        "costs_bp": COSTS,
        "executions": EXECUTIONS,
        "bootstrap_seed": SEED,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    actual_primary = actual_df[(actual_df.cost_bp == 10.0) & (actual_df.execution == "next_open")]
    long_primary = long_df[(long_df.cost_bp == 10.0) & (long_df.execution == "next_open")]
    report = [
        "# Gold instrument ablation result",
        "",
        f"Decision: **{decision}**",
        "",
        "## Stage 1 — actual ETF overlap (primary)",
        "",
        actual_primary[["candidate", "months", "start", "end", "cagr", "sharpe", "mdd", "calmar", "annual_turnover"]].to_markdown(index=False),
        "",
        f"Bootstrap P[Sharpe(SPOT)>Sharpe(FUTURES)]: **{prob:.3f}**",
        "",
        "### Actual gates",
        *[f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in actual_checks.items()],
        "",
        "## Stage 2 — synthetic unhedged physical-gold proxy",
        "",
        f"Proxy monthly-return correlation vs 411060: **{proxy['monthly_return_correlation']:.4f}**",
        f"Proxy annualized tracking error vs 411060: **{proxy['annualized_tracking_error']:.2%}**",
        f"Proxy validation: **{'PASS' if proxy_ok else 'FAIL'}**",
        "",
        long_primary[["candidate", "months", "start", "end", "cagr", "sharpe", "mdd", "calmar", "annual_turnover"]].to_markdown(index=False),
        "",
        "### Long-history gates",
        *[f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in long_checks.items()],
        "",
        "## Interpretation rule",
        "",
        "This report follows PROTOCOL.md frozen before results. No SMA/weight/threshold is changed from the observed result.",
    ]
    (OUT / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print((OUT / "REPORT.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
