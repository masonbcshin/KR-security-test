from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import backtest as bt

OUT = Path("balanced_trend_v2/out_final")
OUT.mkdir(parents=True, exist_ok=True)
GRID = tuple(bt.SMA_GRID)
LABEL_A = "A_current_v1"
LABEL_Z = "Z_static_fixed"
LABEL_F = "F_sma_grid_ensemble"


def ensemble_signal(raw: pd.DataFrame, signal_date: pd.Timestamp) -> pd.Series:
    votes = pd.Series(0.0, index=bt.RISK)
    for n in GRID:
        votes += bt.sma_sig(raw, signal_date, n)
    return votes / len(GRID)


def make_periods(raw: pd.DataFrame, adj: pd.DataFrame, aopen: pd.DataFrame, execution: str):
    idx = raw.index
    warmup = max(253, max(GRID))
    ends = [d for d in bt.month_ends(idx) if idx.get_loc(d) >= warmup]
    rebs = [(d, bt.next_day(idx, d)) for d in ends]
    rebs = [(d, r) for d, r in rebs if r is not None]
    px = aopen if execution == "next_open" else adj

    rows = []
    ta, tz, tf = [], [], []
    for i in range(len(rebs) - 1):
        signal_date, rebalance_date = rebs[i]
        _, next_rebalance = rebs[i + 1]
        asset_ret = px.loc[next_rebalance, bt.ALL] / px.loc[rebalance_date, bt.ALL] - 1.0
        rows.append({
            "date": rebalance_date,
            **{f"r_{s}": float(asset_ret[s]) for s in bt.ALL},
        })
        ta.append(pd.Series(bt.target(LABEL_A, raw, adj, signal_date, sma=200), name=rebalance_date))
        tz.append(pd.Series(bt.BASE.reindex(bt.ALL), name=rebalance_date))
        tf.append(pd.Series(bt.compose(bt.BASE[bt.RISK], ensemble_signal(raw, signal_date)), name=rebalance_date))

    p = pd.DataFrame(rows).set_index("date")
    targets = {
        LABEL_A: pd.DataFrame(ta).reindex(p.index),
        LABEL_Z: pd.DataFrame(tz).reindex(p.index),
        LABEL_F: pd.DataFrame(tf).reindex(p.index),
    }
    return p, targets


def main() -> None:
    raw, adj, aopen = bt.download()
    metrics = []
    sims: dict[tuple[str, float, str], pd.DataFrame] = {}

    for execution in bt.EXECUTIONS:
        periods, targets = make_periods(raw, adj, aopen, execution)
        for cost in bt.COSTS:
            for label in (LABEL_A, LABEL_Z, LABEL_F):
                sim = bt.simulate(periods, targets[label], label, cost)
                sims[(label, cost, execution)] = sim
                for window in ("FULL", "EARLY", "OOS"):
                    m = bt.stats(sim, window)
                    m.update(candidate=label, cost_bp=cost, execution=execution)
                    metrics.append(m)

    mf = pd.DataFrame(metrics)
    mf.to_csv(OUT / "final_metrics.csv", index=False)

    def row(label: str, cost: float = 10.0, execution: str = "next_open") -> pd.Series:
        z = mf[(mf.candidate == label) & (mf.cost_bp == cost) &
               (mf.execution == execution) & (mf.window == "OOS")]
        if len(z) != 1:
            raise RuntimeError(f"metric row mismatch: {label} {cost} {execution} rows={len(z)}")
        return z.iloc[0]

    a10, z10, f10 = row(LABEL_A), row(LABEL_Z), row(LABEL_F)
    a25, z25, f25 = row(LABEL_A, 25.0), row(LABEL_Z, 25.0), row(LABEL_F, 25.0)
    ac, zc, fc = row(LABEL_A, 10.0, "next_close"), row(LABEL_Z, 10.0, "next_close"), row(LABEL_F, 10.0, "next_close")

    prob_f_a = bt.bootstrap_prob(
        sims[(LABEL_F, 10.0, "next_open")],
        sims[(LABEL_A, 10.0, "next_open")],
    )
    prob_f_z = bt.bootstrap_prob(
        sims[(LABEL_F, 10.0, "next_open")],
        sims[(LABEL_Z, 10.0, "next_open")],
    )

    checks = {
        "primary_sharpe_gt_A_and_Z": float(f10.sharpe) > max(float(a10.sharpe), float(z10.sharpe)),
        "primary_calmar_ge_A": float(f10.calmar) >= float(a10.calmar),
        "primary_mdd_not_20pct_worse_than_A": abs(float(f10.mdd)) <= 1.2 * abs(float(a10.mdd)),
        "cost25_sharpe_gt_A_and_Z": float(f25.sharpe) > max(float(a25.sharpe), float(z25.sharpe)),
        "next_close_sharpe_gt_A_and_Z": float(fc.sharpe) > max(float(ac.sharpe), float(zc.sharpe)),
        "bootstrap_F_gt_A_ge_70pct": prob_f_a >= 0.70,
        "bootstrap_F_gt_Z_ge_70pct": prob_f_z >= 0.70,
    }
    passed = all(checks.values())
    verdict = {
        "decision": "PROMOTE_F_SMA_GRID_ENSEMBLE" if passed else "NO_STATISTICALLY_VALIDATED_OPTIMUM",
        "candidate": LABEL_F,
        "grid": list(GRID),
        "checks": checks,
        "bootstrap_prob_sharpe_F_gt_A": prob_f_a,
        "bootstrap_prob_sharpe_F_gt_Z": prob_f_z,
        "primary": {
            label: {k: float(row(label)[k]) for k in ("cagr", "sharpe", "mdd", "calmar", "annual_turnover")}
            for label in (LABEL_A, LABEL_Z, LABEL_F)
        },
        "cost25_sharpe": {label: float(row(label, 25.0).sharpe) for label in (LABEL_A, LABEL_Z, LABEL_F)},
        "next_close_sharpe": {label: float(row(label, 10.0, "next_close").sharpe) for label in (LABEL_A, LABEL_Z, LABEL_F)},
    }
    (OUT / "FINAL_VERDICT.json").write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")

    primary = mf[(mf.window == "OOS") & (mf.execution == "next_open") & (mf.cost_bp == 10.0)]
    primary = primary.sort_values("sharpe", ascending=False)
    report = [
        "# Final SMA-grid ensemble audit",
        "",
        f"Decision: **{verdict['decision']}**",
        "",
        f"Frozen grid: `{list(GRID)}`",
        "",
        "## Primary OOS — next-open, 10bp",
        "",
        primary[["candidate", "cagr", "sharpe", "mdd", "calmar", "annual_turnover"]].to_markdown(index=False),
        "",
        "## Stress Sharpe",
        "",
        f"- 25bp next-open — A: {float(a25.sharpe):.3f}, Z: {float(z25.sharpe):.3f}, F: {float(f25.sharpe):.3f}",
        f"- 10bp next-close — A: {float(ac.sharpe):.3f}, Z: {float(zc.sharpe):.3f}, F: {float(fc.sharpe):.3f}",
        "",
        "## Paired block bootstrap",
        "",
        f"- P[Sharpe(F)>Sharpe(A)]: **{prob_f_a:.3f}**",
        f"- P[Sharpe(F)>Sharpe(Z)]: **{prob_f_z:.3f}**",
        "",
        "## Frozen gates",
    ] + [f"- {name}: {'PASS' if ok else 'FAIL'}" for name, ok in checks.items()]
    (OUT / "FINAL_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print((OUT / "FINAL_REPORT.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
