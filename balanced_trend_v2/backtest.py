from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

RISK = ["069500.KS", "143850.KS", "148070.KS", "132030.KS"]
CASH = "153130.KS"
ALL = RISK + [CASH]
BASE = pd.Series({"069500.KS": .30, "143850.KS": .30, "148070.KS": .15,
                  "132030.KS": .15, CASH: .10}, dtype=float)
CANDS = ["A_current_v1", "B_sma200_inverse_vol", "C_multihorizon_fixed",
         "D_multihorizon_inverse_vol", "E_robust_risk_managed"]
OOS = pd.Timestamp("2020-01-01")
HORIZONS = (63, 126, 252)
ALT_HORIZONS = [(42, 126, 252), (63, 126, 252), (63, 189, 252)]
SMA_GRID = [160, 180, 200, 220, 240]
COSTS = [10.0, 25.0, 50.0]
EXECUTIONS = ["next_open", "next_close"]
TARGET_VOL = .10
BAND = .025
SEED = 20260826


def download() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw, adj, aopen = {}, {}, {}
    for s in ALL:
        d = yf.download(s, start="2010-01-01", auto_adjust=False, actions=True,
                        progress=False, threads=False, timeout=30)
        if isinstance(d.columns, pd.MultiIndex):
            if s in d.columns.get_level_values(-1):
                d = d.xs(s, level=-1, axis=1)
            elif s in d.columns.get_level_values(0):
                d = d.xs(s, level=0, axis=1)
        if d.empty or not {"Open", "Close", "Adj Close"}.issubset(d.columns):
            raise RuntimeError(f"missing Yahoo data for {s}: {list(d.columns)}")
        d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
        close = pd.to_numeric(d["Close"], errors="coerce")
        ac = pd.to_numeric(d["Adj Close"], errors="coerce")
        op = pd.to_numeric(d["Open"], errors="coerce")
        raw[s], adj[s], aopen[s] = close, ac, op * ac / close.replace(0, np.nan)
    raw, adj, aopen = pd.DataFrame(raw), pd.DataFrame(adj), pd.DataFrame(aopen)
    idx = raw.dropna().index.intersection(adj.dropna().index).intersection(aopen.dropna().index)
    raw, adj, aopen = raw.loc[idx, ALL], adj.loc[idx, ALL], aopen.loc[idx, ALL]
    if len(idx) < 600 or (raw <= 0).any().any() or (adj <= 0).any().any():
        raise RuntimeError(f"invalid common data: rows={len(idx)}")
    return raw, adj, aopen


def month_ends(idx: pd.DatetimeIndex) -> list[pd.Timestamp]:
    s = pd.Series(idx, index=idx)
    return [pd.Timestamp(x) for x in s.groupby(idx.to_period("M")).last().tolist()]


def next_day(idx: pd.DatetimeIndex, d: pd.Timestamp) -> pd.Timestamp | None:
    i = idx.searchsorted(d, side="right")
    return pd.Timestamp(idx[i]) if i < len(idx) else None


def sma_sig(raw: pd.DataFrame, d: pd.Timestamp, n: int = 200) -> pd.Series:
    h = raw.loc[:d, RISK]
    if len(h) < n:
        raise ValueError("SMA history short")
    return (h.iloc[-1] >= h.tail(n).mean()).astype(float)


def multi_sig(raw: pd.DataFrame, d: pd.Timestamp, hz=HORIZONS) -> pd.Series:
    h = raw.loc[:d, RISK]
    if len(h) <= max(hz):
        raise ValueError("momentum history short")
    out = pd.Series(0.0, index=RISK)
    for n in hz:
        out += (h.iloc[-1] / h.iloc[-1-n] - 1 > 0).astype(float)
    return out / len(hz)


def invvol(adj: pd.DataFrame, d: pd.Timestamp) -> pd.Series:
    r = adj.loc[:d, RISK].pct_change(fill_method=None).dropna().tail(126)
    if len(r) < 126:
        raise ValueError("vol history short")
    v = r.std(ddof=1) * math.sqrt(252)
    x = 1 / v
    return .90 * x / x.sum()


def compose(base: pd.Series, sig: pd.Series) -> pd.Series:
    w = pd.Series(0.0, index=ALL)
    w[RISK] = base.reindex(RISK) * sig.reindex(RISK)
    w[CASH] = 1 - w[RISK].sum()
    if (w < -1e-10).any() or abs(w.sum() - 1) > 1e-8:
        raise ValueError(w.to_dict())
    return w


def target(c: str, raw: pd.DataFrame, adj: pd.DataFrame, d: pd.Timestamp,
           *, sma=200, hz=HORIZONS) -> pd.Series:
    if c == "A_current_v1":
        return compose(BASE[RISK], sma_sig(raw, d, sma))
    if c == "B_sma200_inverse_vol":
        return compose(invvol(adj, d), sma_sig(raw, d, sma))
    if c == "C_multihorizon_fixed":
        return compose(BASE[RISK], multi_sig(raw, d, hz))
    if c in ("D_multihorizon_inverse_vol", "E_robust_risk_managed"):
        w = compose(invvol(adj, d), multi_sig(raw, d, hz))
        if c == "E_robust_risk_managed":
            r = adj.loc[:d, RISK].pct_change(fill_method=None).dropna().tail(63)
            cov = r.cov() * 252
            x = w[RISK].to_numpy()
            vol = math.sqrt(max(float(x @ cov.to_numpy() @ x), 0.0))
            scale = min(1.0, TARGET_VOL / vol) if vol > 0 else 1.0
            w[RISK] *= scale
            w[CASH] = 1 - w[RISK].sum()
        return w
    raise KeyError(c)


def banded(t: pd.Series, cur: pd.Series) -> pd.Series:
    w = t.copy()
    for s in RISK:
        if abs(float(t[s] - cur[s])) < BAND:
            w[s] = cur[s]
    w[CASH] = 1 - w[RISK].sum()
    return w


def periods(raw: pd.DataFrame, adj: pd.DataFrame, aopen: pd.DataFrame,
            execution: str, *, sma=200, hz=HORIZONS):
    idx = raw.index
    ends = [d for d in month_ends(idx) if idx.get_loc(d) >= max(253, sma)]
    rebs = [(d, next_day(idx, d)) for d in ends]
    rebs = [(d, r) for d, r in rebs if r is not None]
    px = aopen if execution == "next_open" else adj
    rows, tgts = [], {c: [] for c in CANDS}
    for i in range(len(rebs)-1):
        sd, rd = rebs[i]
        _, nrd = rebs[i+1]
        ar = px.loc[nrd, ALL] / px.loc[rd, ALL] - 1
        rows.append({"date": rd, **{f"r_{s}": float(ar[s]) for s in ALL}})
        for c in CANDS:
            tgts[c].append(pd.Series(target(c, raw, adj, sd, sma=sma, hz=hz), name=rd))
    p = pd.DataFrame(rows).set_index("date")
    return p, {c: pd.DataFrame(v).reindex(p.index) for c, v in tgts.items()}


def simulate(p: pd.DataFrame, t: pd.DataFrame, c: str, bp: float) -> pd.DataFrame:
    cur = pd.Series(0.0, index=ALL); cur[CASH] = 1.0
    out = []
    for d, row in p.iterrows():
        w = t.loc[d, ALL].astype(float)
        if c == "E_robust_risk_managed":
            w = banded(w, cur)
        turnover = float((w-cur).abs().sum())
        cost = turnover * bp / 10000.0
        ar = pd.Series({s: float(row[f"r_{s}"]) for s in ALL})
        gross = float((w*ar).sum())
        net = (1-cost)*(1+gross)-1
        cur = w*(1+ar)/(1+gross)
        out.append({"date": d, "return": net, "rf": float(ar[CASH]),
                    "turnover": turnover, "cost": cost})
    return pd.DataFrame(out).set_index("date")


def stats(x: pd.DataFrame, window: str) -> dict:
    if window == "OOS": x = x.loc[x.index >= OOS]
    elif window == "EARLY": x = x.loc[x.index < OOS]
    if len(x) < 12: return {"window": window, "months": len(x)}
    r, rf = x["return"], x["rf"]
    ex = r-rf; n = len(r); eq=(1+r).cumprod()
    cagr=float(eq.iloc[-1]**(12/n)-1)
    sd=float(ex.std(ddof=1)*math.sqrt(12))
    sharpe=float(ex.mean()*12/sd) if sd else np.nan
    dd=eq/eq.cummax()-1; mdd=float(dd.min())
    roll12=(1+r).rolling(12).apply(np.prod, raw=True)-1
    roll36=(1+r).rolling(36).apply(np.prod, raw=True)**(1/3)-1
    return {"window": window, "months": n, "start": str(x.index.min().date()),
            "end": str(x.index.max().date()), "cagr": cagr,
            "sharpe": sharpe, "mdd": mdd,
            "calmar": cagr/abs(mdd) if mdd < 0 else np.nan,
            "worst_12m": float(roll12.min()), "worst_36m_cagr": float(roll36.min()),
            "rolling_36m_positive_ratio": float((roll36.dropna()>0).mean()),
            "annual_turnover": float(x.turnover.sum()/(n/12))}


def bootstrap_prob(c: pd.DataFrame, a: pd.DataFrame, nboot=2000) -> float:
    idx=c.index.intersection(a.index); idx=idx[idx>=OOS]
    cr=c.loc[idx,"return"].to_numpy(); ar=a.loc[idx,"return"].to_numpy(); rf=c.loc[idx,"rf"].to_numpy()
    n=len(idx); rng=np.random.default_rng(SEED); win=0
    def sh(r, take):
        e=r[take]-rf[take]; sd=e.std(ddof=1)
        return e.mean()/sd*math.sqrt(12) if sd else np.nan
    for _ in range(nboot):
        take=[]
        while len(take)<n:
            st=int(rng.integers(0,n)); take += [(st+j)%n for j in range(12)]
        take=np.array(take[:n]); win += bool(sh(cr,take)>sh(ar,take))
    return win/nboot


def main():
    out=Path("balanced_trend_v2/out"); out.mkdir(parents=True, exist_ok=True)
    raw, adj, aopen=download()
    manifest={"provider":"Yahoo Finance via yfinance","common_start":str(raw.index.min().date()),
              "common_end":str(raw.index.max().date()),"common_rows":len(raw),"symbols":ALL}
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False))

    metrics=[]; sims={}
    for exe in EXECUTIONS:
        p,t=periods(raw,adj,aopen,exe)
        for bp in COSTS:
            for c in CANDS:
                sim=simulate(p,t[c],c,bp); sims[(c,bp,exe)]=sim
                for win in ("FULL","EARLY","OOS"):
                    m=stats(sim,win); m.update(candidate=c,cost_bp=bp,execution=exe); metrics.append(m)
    mf=pd.DataFrame(metrics); mf.to_csv(out/"metrics.csv",index=False)

    sens=[]
    for n in SMA_GRID:
        p,t=periods(raw,adj,aopen,"next_open",sma=n)
        m=stats(simulate(p,t["A_current_v1"],"A_current_v1",10),"OOS"); m["sma"]=n; sens.append(m)
    pd.DataFrame(sens).to_csv(out/"sensitivity_sma.csv",index=False)

    es=[]
    for hz in ALT_HORIZONS:
        p,t=periods(raw,adj,aopen,"next_open",hz=hz)
        m=stats(simulate(p,t["E_robust_risk_managed"],"E_robust_risk_managed",10),"OOS")
        m["horizons"]="/".join(map(str,hz)); es.append(m)
    esf=pd.DataFrame(es); esf.to_csv(out/"sensitivity_e.csv",index=False)

    def row(c,bp=10,exe="next_open"):
        z=mf[(mf.candidate==c)&(mf.cost_bp==bp)&(mf.execution==exe)&(mf.window=="OOS")]
        return z.iloc[0]
    a10=row("A_current_v1"); a25=row("A_current_v1",25); ac=row("A_current_v1",10,"next_close")
    verdict={"benchmark":"A_current_v1","candidates":{}}
    eligible=[]
    for c in CANDS[1:]:
        x=row(c); x25=row(c,25); xc=row(c,10,"next_close")
        prob=bootstrap_prob(sims[(c,10,"next_open")],sims[("A_current_v1",10,"next_open")])
        hz_ok=True
        if c=="E_robust_risk_managed": hz_ok=int((esf.sharpe>float(a10.sharpe)).sum())>=2
        checks={"sharpe_gt_A":float(x.sharpe)>float(a10.sharpe),
                "calmar_ge_A":float(x.calmar)>=float(a10.calmar),
                "mdd_not_20pct_worse":abs(float(x.mdd))<=1.2*abs(float(a10.mdd)),
                "cost25_sharpe_gt_A":float(x25.sharpe)>float(a25.sharpe),
                "next_close_sharpe_gt_A":float(xc.sharpe)>float(ac.sharpe),
                "bootstrap_ge_70pct":prob>=.70,"horizon_robustness":hz_ok}
        passed=all(checks.values())
        verdict["candidates"][c]={"passed":passed,"checks":checks,"bootstrap_prob":prob,
                                   "oos_sharpe":float(x.sharpe),"oos_calmar":float(x.calmar),
                                   "oos_cagr":float(x.cagr),"oos_mdd":float(x.mdd)}
        if passed: eligible.append(c)
    if eligible:
        eligible.sort(key=lambda c:(verdict["candidates"][c]["oos_sharpe"],verdict["candidates"][c]["oos_calmar"]),reverse=True)
        verdict["decision"]="PROMOTE"; verdict["winner"]=eligible[0]
    else:
        verdict["decision"]="KEEP_V1"; verdict["winner"]="A_current_v1"
    (out/"verdict.json").write_text(json.dumps(verdict,indent=2,ensure_ascii=False))

    rank=mf[(mf.execution=="next_open")&(mf.cost_bp==10)&(mf.window=="OOS")].sort_values("sharpe",ascending=False)
    rank.to_csv(out/"primary_rank.csv",index=False)
    report=["# Balanced Trend Tournament v2", "", f"Decision: **{verdict['decision']}**", f"Winner: **{verdict['winner']}**", "",
            "## Primary OOS (next-open, 10bp)", "", rank[["candidate","cagr","sharpe","mdd","calmar","annual_turnover"]].to_markdown(index=False), "",
            "## Promotion checks", ""]
    for c,v in verdict["candidates"].items():
        report += [f"### {c}",f"passed: **{v['passed']}**, bootstrap P(Sharpe>A)={v['bootstrap_prob']:.3f}"]+[f"- {k}: {'PASS' if ok else 'FAIL'}" for k,ok in v['checks'].items()]+[""]
    (out/"REPORT.md").write_text("\n".join(report))
    print((out/"REPORT.md").read_text())

if __name__=="__main__": main()
