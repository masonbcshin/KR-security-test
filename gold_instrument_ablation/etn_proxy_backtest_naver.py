from __future__ import annotations

import json
import math
import re
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

import backtest as bt

ETN = "530067.KS"
ETN_CODE = "530067"
OUT = Path("gold_instrument_ablation/out_etn")


def download_naver_etn() -> pd.DataFrame:
    url = (
        "https://fchart.stock.naver.com/sise.nhn?timeframe=day&count=6000&"
        f"requestType=0&symbol={ETN_CODE}"
    )
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    items = re.findall(r'<item data="(.*?)" />', r.text, re.DOTALL)
    if len(items) < 250:
        raise RuntimeError(f"insufficient Naver history for {ETN_CODE}: {len(items)}")
    df = pd.read_csv(StringIO("\n".join(items)), delimiter="|", header=None)
    df.columns = ["Date", "Open", "High", "Low", "Close", "Volume"]
    df["Date"] = pd.to_datetime(df["Date"].astype(str), format="%Y%m%d")
    df = df.set_index("Date").sort_index()
    for col in ("Open", "Close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Open", "Close"])
    df["Adj Close"] = df["Close"]
    df["Adj Open"] = df["Open"]
    if (df[["Close", "Adj Close", "Adj Open"]] <= 0).any().any():
        raise RuntimeError("invalid non-positive Naver ETN prices")
    return df[["Open", "Close", "Adj Close", "Adj Open"]]


def assemble(data: dict[str, pd.DataFrame], symbols: list[str]):
    common = None
    for s in symbols:
        common = data[s].index if common is None else common.intersection(data[s].index)
    idx = pd.DatetimeIndex(common).sort_values()
    raw = pd.DataFrame({s: data[s].loc[idx, "Close"] for s in symbols})
    adj = pd.DataFrame({s: data[s].loc[idx, "Adj Close"] for s in symbols})
    aopen = pd.DataFrame({s: data[s].loc[idx, "Adj Open"] for s in symbols})
    return raw, adj, aopen


def proxy_validation(data: dict[str, pd.DataFrame]) -> dict:
    a = bt.monthly_returns(data[bt.SPOT_GOLD]["Adj Close"])
    b = bt.monthly_returns(data[ETN]["Adj Close"])
    idx = a.index.intersection(b.index)
    if len(idx) < 24:
        raise RuntimeError(f"too few overlap months for proxy validation: {len(idx)}")
    a, b = a.loc[idx], b.loc[idx]
    corr = float(a.corr(b))
    te = float((a - b).std(ddof=1) * math.sqrt(12))
    return {
        "months": len(idx),
        "start": str(idx.min().date()),
        "end": str(idx.max().date()),
        "monthly_return_correlation": corr,
        "annualized_tracking_error": te,
        "corr_ge_098": corr >= 0.98,
        "tracking_error_le_004": te <= 0.04,
        "etn_source": "Naver fchart raw OHLC; no distribution adjustment",
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    symbols_yahoo = bt.KOREAN_FIXED + [bt.FUT_GOLD, bt.SPOT_GOLD]
    data = {s: bt.download_one(s, "2010-01-01") for s in symbols_yahoo}
    data[ETN] = download_naver_etn()

    validation = proxy_validation(data)
    (OUT / "proxy_validation.json").write_text(
        json.dumps(validation, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    long_symbols = bt.KOREAN_FIXED + [bt.FUT_GOLD, ETN]
    raw, adj, aopen = assemble(data, long_symbols)
    metrics = []
    sims = {}
    labels = {bt.FUT_GOLD: "G_FUTURES_H", ETN: "G_KRX_SPOT_ETN_PROXY"}

    for exe in bt.EXECUTIONS:
        for gold in (bt.FUT_GOLD, ETN):
            p, t = bt.periods(raw, adj, aopen, exe, gold)
            for cost in bt.COSTS:
                sim = bt.simulate(p, t, cost)
                sims[(labels[gold], cost, exe)] = sim
                m = bt.stats(sim)
                m.update(
                    candidate=labels[gold],
                    gold_symbol=gold,
                    cost_bp=cost,
                    execution=exe,
                )
                metrics.append(m)

    df = pd.DataFrame(metrics)
    df.to_csv(OUT / "metrics.csv", index=False)

    def row(label: str, cost=10.0, exe="next_open"):
        z = df[
            (df.candidate == label)
            & (df.cost_bp == cost)
            & (df.execution == exe)
        ]
        if len(z) != 1:
            raise RuntimeError(f"row mismatch {label} {cost} {exe}: {len(z)}")
        return z.iloc[0]

    f10, s10 = row("G_FUTURES_H"), row("G_KRX_SPOT_ETN_PROXY")
    f25, s25 = row("G_FUTURES_H", 25.0), row("G_KRX_SPOT_ETN_PROXY", 25.0)
    f50, s50 = row("G_FUTURES_H", 50.0), row("G_KRX_SPOT_ETN_PROXY", 50.0)
    fc, sc = row("G_FUTURES_H", 10.0, "next_close"), row(
        "G_KRX_SPOT_ETN_PROXY", 10.0, "next_close"
    )
    prob = bt.bootstrap_prob(
        sims[("G_KRX_SPOT_ETN_PROXY", 10.0, "next_open")],
        sims[("G_FUTURES_H", 10.0, "next_open")],
        block=12,
        nboot=4000,
    )

    checks = {
        "sharpe_spot_proxy_gt_futures": float(s10.sharpe) > float(f10.sharpe),
        "calmar_spot_proxy_ge_futures": float(s10.calmar) >= float(f10.calmar),
        "mdd_spot_proxy_no_more_than_10pct_worse": abs(float(s10.mdd))
        <= 1.10 * abs(float(f10.mdd)),
        "cost25_sharpe_spot_proxy_gt_futures": float(s25.sharpe) > float(f25.sharpe),
        "cost50_sharpe_spot_proxy_gt_futures": float(s50.sharpe) > float(f50.sharpe),
        "next_close_sharpe_spot_proxy_gt_futures": float(sc.sharpe) > float(fc.sharpe),
        "bootstrap_ge_70pct": prob >= 0.70,
    }
    validation_ok = bool(validation["corr_ge_098"] and validation["tracking_error_le_004"])
    decision = (
        "KRX_SPOT_LONG_PROXY_SUPPORTS_REPLACEMENT"
        if validation_ok and all(checks.values())
        else "KRX_SPOT_LONG_PROXY_NOT_CONFIRMED"
    )

    verdict = {
        "decision": decision,
        "validation": validation,
        "checks": checks,
        "bootstrap_prob_sharpe_spot_proxy_gt_futures": prob,
        "common_daily_start": str(raw.index.min().date()),
        "common_daily_end": str(raw.index.max().date()),
        "common_daily_rows": len(raw),
        "primary": {
            "G_FUTURES_H": {
                k: float(f10[k])
                for k in ("cagr", "sharpe", "mdd", "calmar", "annual_turnover")
            },
            "G_KRX_SPOT_ETN_PROXY": {
                k: float(s10[k])
                for k in ("cagr", "sharpe", "mdd", "calmar", "annual_turnover")
            },
        },
    }
    (OUT / "verdict.json").write_text(
        json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    primary = df[(df.cost_bp == 10.0) & (df.execution == "next_open")]
    report = [
        "# KRX Gold Spot ETN proxy confirmation",
        "",
        f"Decision: **{decision}**",
        "",
        f"Proxy validation correlation vs 411060: **{validation['monthly_return_correlation']:.4f}**",
        f"Proxy validation annualized tracking error vs 411060: **{validation['annualized_tracking_error']:.2%}**",
        f"Proxy validation: **{'PASS' if validation_ok else 'FAIL'}**",
        "",
        primary[
            [
                "candidate",
                "months",
                "start",
                "end",
                "cagr",
                "sharpe",
                "mdd",
                "calmar",
                "annual_turnover",
            ]
        ].to_markdown(index=False),
        "",
        f"Bootstrap P[Sharpe(spot ETN proxy)>Sharpe(futures)]: **{prob:.3f}**",
        "",
        "## Gates",
        *[f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in checks.items()],
    ]
    (OUT / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print((OUT / "REPORT.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
