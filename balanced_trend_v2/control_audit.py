from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import backtest as bt

OUT = Path("balanced_trend_v2/out_control")
OUT.mkdir(parents=True, exist_ok=True)


def static_targets(index: pd.Index) -> pd.DataFrame:
    return pd.DataFrame([bt.BASE.reindex(bt.ALL).to_dict() for _ in index], index=index)


def one_run(raw, adj, aopen, execution: str, cost: float):
    p, targets = bt.periods(raw, adj, aopen, execution)
    a = bt.simulate(p, targets["A_current_v1"], "A_current_v1", cost)
    z = bt.simulate(p, static_targets(p.index), "Z_static_fixed", cost)
    return a, z


def main():
    raw, adj, aopen = bt.download()
    rows = []
    sims = {}
    for exe in bt.EXECUTIONS:
        for cost in bt.COSTS:
            a, z = one_run(raw, adj, aopen, exe, cost)
            sims[("A", cost, exe)] = a
            sims[("Z", cost, exe)] = z
            for label, sim in (("A_current_v1", a), ("Z_static_fixed", z)):
                for window in ("FULL", "EARLY", "OOS"):
                    m = bt.stats(sim, window)
                    m.update(candidate=label, cost_bp=cost, execution=exe)
                    rows.append(m)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "control_metrics.csv", index=False)

    def row(label: str, cost=10.0, exe="next_open"):
        z = df[(df.candidate == label) & (df.cost_bp == cost) &
               (df.execution == exe) & (df.window == "OOS")]
        return z.iloc[0]

    a10, z10 = row("A_current_v1"), row("Z_static_fixed")
    a25, z25 = row("A_current_v1", 25.0), row("Z_static_fixed", 25.0)
    ac, zc = row("A_current_v1", 10.0, "next_close"), row("Z_static_fixed", 10.0, "next_close")
    prob = bt.bootstrap_prob(sims[("A", 10.0, "next_open")], sims[("Z", 10.0, "next_open")])

    checks = {
        "oos_sharpe_A_gt_Z": float(a10.sharpe) > float(z10.sharpe),
        "oos_calmar_A_ge_Z": float(a10.calmar) >= float(z10.calmar),
        "oos_mdd_A_no_worse": abs(float(a10.mdd)) <= abs(float(z10.mdd)),
        "cost25_sharpe_A_gt_Z": float(a25.sharpe) > float(z25.sharpe),
        "next_close_sharpe_A_gt_Z": float(ac.sharpe) > float(zc.sharpe),
        "bootstrap_prob_ge_70pct": prob >= 0.70,
    }
    verdict = {
        "decision": "V1_TREND_FILTER_VALIDATED" if all(checks.values()) else "V1_TREND_FILTER_NOT_VALIDATED",
        "checks": checks,
        "bootstrap_prob_sharpe_A_gt_Z": prob,
        "A_oos": {k: float(a10[k]) for k in ("cagr", "sharpe", "mdd", "calmar", "annual_turnover")},
        "Z_oos": {k: float(z10[k]) for k in ("cagr", "sharpe", "mdd", "calmar", "annual_turnover")},
    }
    (OUT / "control_verdict.json").write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")

    primary = df[(df.window == "OOS") & (df.execution == "next_open") & (df.cost_bp == 10.0)]
    report = [
        "# v1 static-control audit",
        "",
        f"Decision: **{verdict['decision']}**",
        "",
        "## Primary OOS",
        "",
        primary[["candidate", "cagr", "sharpe", "mdd", "calmar", "annual_turnover"]].to_markdown(index=False),
        "",
        f"Bootstrap P[Sharpe(A)>Sharpe(Z)]: **{prob:.3f}**",
        "",
        "## Gates",
    ] + [f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in checks.items()]
    (OUT / "CONTROL_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print((OUT / "CONTROL_REPORT.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
