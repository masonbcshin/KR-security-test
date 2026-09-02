#!/usr/bin/env python3
from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm, skew, kurtosis
from pykrx import stock as krx_stock

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
OUT.mkdir(parents=True, exist_ok=True)
DOWNLOAD_START = "2016-01-01"
EVAL_START = pd.Timestamp("2018-01-02")
COST_BPS = [11.5, 25.0, 50.0]
EXECUTIONS = ["next_close", "next_open"]
TAX_RATE = 0.154
BOOTSTRAPS = 2000
SEED = 20260902

TICKERS = {
    "K200": "069500.KS", "SP500H": "143850.KS", "KTB10": "148070.KS",
    "GOLDH": "132030.KS", "SHORT": "153130.KS",
    "KOSPI_ETF": "226490.KS", "KOSDAQ150_ETF": "229200.KS", "SHORT_PLUS": "214980.KS",
}
BASE = {"K200": .30, "SP500H": .30, "KTB10": .15, "GOLDH": .15, "SHORT": .10}
RISK = ["K200", "SP500H", "KTB10", "GOLDH"]
SMA_GRID = [160, 180, 200, 220, 240]
TAXABLE = {"SP500H", "KTB10", "GOLDH", "SHORT", "SHORT_PLUS"}
STRATEGIES = ["PQ_CORE_60_40_214980_V1", "STATIC_30_30_15_15_10", "BALANCED_TREND_V1", "BALANCED_TREND_V2F"]


def normalize(w: Dict[str, float]) -> dict[str, float]:
    w = {k: max(float(v), 0.0) for k, v in w.items() if float(v) > 1e-14}
    s = sum(w.values())
    if s <= 0:
        raise ValueError("empty target")
    return {k: v / s for k, v in w.items()}


def download_prices():
    raw = yf.download(list(TICKERS.values()), start=DOWNLOAD_START, auto_adjust=False, progress=False, threads=False)
    if raw.empty or not isinstance(raw.columns, pd.MultiIndex):
        raise RuntimeError("Yahoo download failed")
    op, cl = {}, {}
    for a, t in TICKERS.items():
        o, c, adj = raw[("Open", t)].astype(float), raw[("Close", t)].astype(float), raw[("Adj Close", t)].astype(float)
        factor = adj / c.replace(0.0, np.nan)
        op[a], cl[a] = o * factor, adj
    op, cl = pd.DataFrame(op).sort_index(), pd.DataFrame(cl).sort_index()
    valid = op.notna().all(axis=1) & cl.notna().all(axis=1)
    op, cl = op.loc[valid], cl.loc[valid]
    if op.empty:
        raise RuntimeError("No common price history")
    op.to_csv(OUT / "adjusted_open.csv")
    cl.to_csv(OUT / "adjusted_close.csv")
    return op, cl


def month_ends(index):
    s = pd.Series(index=index, data=index)
    return [pd.Timestamp(x) for x in s.groupby(index.to_period("M")).last().values]


def next_day(index, d):
    p = index.searchsorted(pd.Timestamp(d), side="right")
    return index[p] if p < len(index) else None


def balanced_targets(close, kind):
    out = {}
    for sd in month_ends(close.index):
        ed = next_day(close.index, sd)
        if ed is None or ed < EVAL_START:
            continue
        w = dict(BASE)
        if kind == "BALANCED_TREND_V1":
            moved = 0.0
            for a in RISK:
                h = close[a].loc[:sd].dropna()
                if len(h) < 200:
                    raise RuntimeError(f"SMA200 warmup missing {a} {sd}")
                target = BASE[a] * float(h.iloc[-1] >= h.iloc[-200:].mean())
                moved += BASE[a] - target
                w[a] = target
            w["SHORT"] = BASE["SHORT"] + moved
        elif kind == "BALANCED_TREND_V2F":
            moved = 0.0
            for a in RISK:
                h = close[a].loc[:sd].dropna()
                if len(h) < 240:
                    raise RuntimeError(f"SMA grid warmup missing {a} {sd}")
                score = np.mean([float(h.iloc[-1] >= h.iloc[-n:].mean()) for n in SMA_GRID])
                target = BASE[a] * float(score)
                moved += BASE[a] - target
                w[a] = target
            w["SHORT"] = BASE["SHORT"] + moved
        elif kind != "STATIC_30_30_15_15_10":
            raise ValueError(kind)
        out[pd.Timestamp(ed)] = normalize(w)
    return out


def pq_splits(signal_dates: Iterable[pd.Timestamp]):
    rows = []
    for ts in signal_dates:
        d = pd.Timestamp(ts).strftime("%Y%m%d")
        kp = krx_stock.get_market_cap_by_ticker(d, market="KOSPI", alternative=True)
        kq = krx_stock.get_market_cap_by_ticker(d, market="KOSDAQ", alternative=True)
        members = krx_stock.get_index_portfolio_deposit_file("2203", d, alternative=True)
        if kp.empty or kq.empty or not members:
            raise RuntimeError(f"KRX split unavailable {d}")
        valid = [x for x in members if x in kq.index]
        a, b = float(kp["시가총액"].sum()), float(kq.loc[valid, "시가총액"].sum())
        if a <= 0 or b <= 0:
            raise RuntimeError(f"invalid cap {d}")
        rows.append({"signal_date": pd.Timestamp(ts), "kospi_market_cap": a, "kosdaq150_market_cap": b,
                     "kospi_share": a/(a+b), "kosdaq150_share": b/(a+b), "kosdaq150_members": len(valid)})
    df = pd.DataFrame(rows).set_index("signal_date")
    df.to_csv(OUT / "pq_market_cap_split.csv")
    return df


def pq_targets(index):
    days = index[index >= EVAL_START]
    signals = [days[i] for i in range(0, len(days)-1, 84)]
    splits = pq_splits(signals)
    out = {}
    for sd, r in splits.iterrows():
        ed = next_day(index, sd)
        if ed is not None:
            out[pd.Timestamp(ed)] = normalize({"KOSPI_ETF": .60*r.kospi_share, "KOSDAQ150_ETF": .60*r.kosdaq150_share, "SHORT_PLUS": .40})
    if len(splits):
        r = splits.iloc[0]
        out[pd.Timestamp(days[0])] = normalize({"KOSPI_ETF": .60*r.kospi_share, "KOSDAQ150_ETF": .60*r.kosdaq150_share, "SHORT_PLUS": .40})
    return out


@dataclass
class Sim:
    equity: pd.Series
    ret: pd.Series
    turnover: pd.Series
    costs: pd.Series
    taxes: pd.Series


def simulate(op, cl, targets, execution, cost_bps, tax_proxy):
    idx, aliases = cl.index[cl.index >= EVAL_START], list(cl.columns)
    shares = pd.Series(0.0, index=aliases)
    basis = pd.Series(np.nan, index=aliases)
    wealth, initialized = 1.0, False
    eq, tos, cos, taxs = {}, {}, {}, {}

    def trade(px, pre, target):
        nonlocal shares, basis
        current_val = shares * px
        current_w = current_val/pre if pre > 0 else current_val*0
        tw = pd.Series(target).reindex(aliases).fillna(0.0)
        to = float((tw-current_w).abs().sum())
        cost = pre*to*cost_bps/10000.0
        tax = 0.0
        sell_value = np.maximum((current_w-tw).values, 0.0)*pre
        if tax_proxy:
            for i,a in enumerate(aliases):
                if a in TAXABLE and sell_value[i] > 0 and shares[a] > 0 and np.isfinite(basis[a]):
                    u = min(float(sell_value[i]/px[a]), float(shares[a]))
                    tax += max(float(px[a]-basis[a]), 0.0)*u*TAX_RATE
        post = max(pre-cost-tax, 1e-12)
        new = tw*post/px
        for a in aliases:
            if new[a] <= 0:
                basis[a] = np.nan
            elif new[a] > shares[a]:
                old_u, buy_u = max(float(shares[a]),0.0), float(new[a]-shares[a])
                old_b = 0.0 if not np.isfinite(basis[a]) else old_u*float(basis[a])
                basis[a] = (old_b + buy_u*float(px[a]))/(old_u+buy_u)
        shares = new
        return to, cost, tax

    for d in idx:
        d = pd.Timestamp(d); o, c = op.loc[d], cl.loc[d]; target = targets.get(d)
        to = cost = tax = 0.0
        if execution == "next_open" and target is not None:
            if not initialized:
                tw = pd.Series(target).reindex(aliases).fillna(0.0)
                shares = tw*wealth/o
                basis = pd.Series(np.where(shares>0,o,np.nan), index=aliases)
                initialized = True
            else:
                pre = float((shares*o).sum())
                to,cost,tax = trade(o,pre,target)
            wealth = float((shares*c).sum())
        else:
            if initialized:
                wealth = float((shares*c).sum())
            if execution == "next_close" and target is not None:
                if not initialized:
                    tw = pd.Series(target).reindex(aliases).fillna(0.0)
                    shares = tw*wealth/c
                    basis = pd.Series(np.where(shares>0,c,np.nan), index=aliases)
                    initialized = True
                    wealth = float((shares*c).sum())
                else:
                    to,cost,tax = trade(c,wealth,target)
                    wealth = float((shares*c).sum())
        eq[d], tos[d], cos[d], taxs[d] = wealth,to,cost,tax
    e = pd.Series(eq).sort_index()
    first = min(targets.keys())
    e = e.loc[first:]
    e = e/float(e.iloc[0])
    return Sim(e,e.pct_change().fillna(0),pd.Series(tos).reindex(e.index).fillna(0),pd.Series(cos).reindex(e.index).fillna(0),pd.Series(taxs).reindex(e.index).fillna(0))


def stats(sim):
    r,e = sim.ret.dropna(),sim.equity
    years = len(r)/252.0
    cagr = float(e.iloc[-1]**(1/years)-1)
    vol = float(r.std(ddof=1)*math.sqrt(252))
    sr = float(r.mean()/r.std(ddof=1)*math.sqrt(252)) if r.std(ddof=1)>0 else np.nan
    dn = r[r<0]
    sortino = float(r.mean()*252/(dn.std(ddof=1)*math.sqrt(252))) if len(dn)>1 and dn.std(ddof=1)>0 else np.nan
    dd = e/e.cummax()-1; mdd=float(dd.min())
    out={"CAGR":cagr,"AnnualVol":vol,"Sharpe":sr,"Sortino":sortino,"MDD":mdd,"Calmar":cagr/abs(mdd) if mdd<0 else np.nan,
         "AnnualTurnover":float(sim.turnover.sum()/years),"TotalCostFrac":float(sim.costs.sum()),"TotalTaxProxyFrac":float(sim.taxes.sum()),"Observations":len(r)}
    for n,label in [(252,"1Y"),(756,"3Y"),(1260,"5Y")]:
        x=(e/e.shift(n))**(252.0/n)-1; x=x.dropna()
        out[f"WorstRolling{label}"]=float(x.min()) if len(x) else np.nan
        out[f"PositiveRolling{label}Pct"]=float((x>0).mean()) if len(x) else np.nan
    for name,a,b in [("2018_2021","2018-01-01","2021-12-31"),("2022_LATEST","2022-01-01",None)]:
        z=e.loc[a:b]
        if len(z)>30:
            rr=z.pct_change().fillna(0); yy=len(rr)/252.0; cg=float((z.iloc[-1]/z.iloc[0])**(1/yy)-1); sh=float(rr.mean()/rr.std(ddof=1)*math.sqrt(252)) if rr.std(ddof=1)>0 else np.nan; md=float((z/z.cummax()-1).min())
            out[f"{name}_CAGR"],out[f"{name}_Sharpe"],out[f"{name}_MDD"] = cg,sh,md
    return out


def dsr(ret,n_trials=8):
    x=ret.dropna().values; t=len(x)
    if t<3 or np.std(x,ddof=1)==0:return np.nan
    sr=np.mean(x)/np.std(x,ddof=1); srstd=math.sqrt((1+.5*sr*sr)/(t-1)); g=.5772156649015329
    srstar=srstd*((1-g)*norm.ppf(1-1/n_trials)+g*norm.ppf(1-1/(n_trials*math.e)))
    den=math.sqrt(max(1e-12,1-float(skew(x,bias=False))*sr+((float(kurtosis(x,fisher=False,bias=False))-1)/4)*sr*sr))
    return float(norm.cdf((sr-srstar)*math.sqrt(t-1)/den))


def sr_arr(x):
    return float(np.mean(x)/np.std(x,ddof=1)) if len(x)>1 and np.std(x,ddof=1)>0 else -np.inf


def cscv_pbo(df,s=8):
    mat=df.dropna().values; n=len(mat); block=n//s
    if block<20:return {"PBO":np.nan,"CSCVCombinations":0}
    mat=mat[:block*s]; lambdas=[]
    for train_blocks in itertools.combinations(range(s),s//2):
        mask=np.zeros(block*s,dtype=bool)
        for b in train_blocks:mask[b*block:(b+1)*block]=True
        tr,te=mat[mask],mat[~mask]
        winner=int(np.argmax([sr_arr(tr[:,j]) for j in range(mat.shape[1])]))
        tes=np.array([sr_arr(te[:,j]) for j in range(mat.shape[1])]); ranks=pd.Series(tes).rank(method="average",ascending=True).values
        omega=min(max(float(ranks[winner]/(mat.shape[1]+1)),1e-6),1-1e-6); lambdas.append(math.log(omega/(1-omega)))
    return {"PBO":float(np.mean(np.array(lambdas)<=0)),"CSCVCombinations":len(lambdas),"MedianLogitOOSRank":float(np.median(lambdas))}


def bootstrap(a,b,block=21,nboot=BOOTSTRAPS):
    x=pd.concat([a,b],axis=1).dropna().values; n=len(x); rng=np.random.default_rng(SEED); wins=0
    for _ in range(nboot):
        ids=[]
        while len(ids)<n:
            st=int(rng.integers(0,n));ids.extend([(st+k)%n for k in range(block)])
        q=x[np.array(ids[:n])];wins+=int(sr_arr(q[:,0])>sr_arr(q[:,1]))
    return wins/nboot


def main():
    op,cl=download_prices(); end=cl.index.max(); print("COMMON_WINDOW",EVAL_START.date(),end.date())
    targets={"PQ_CORE_60_40_214980_V1":pq_targets(cl.index),"STATIC_30_30_15_15_10":balanced_targets(cl,"STATIC_30_30_15_15_10"),"BALANCED_TREND_V1":balanced_targets(cl,"BALANCED_TREND_V1"),"BALANCED_TREND_V2F":balanced_targets(cl,"BALANCED_TREND_V2F")}
    rows=[]; primary_ret={}; calendars={}
    for exe,cost,tax in itertools.product(EXECUTIONS,COST_BPS,[False,True]):
        for st in STRATEGIES:
            sim=simulate(op,cl,targets[st],exe,cost,tax); z=stats(sim);z.update({"Strategy":st,"Execution":exe,"CostBps":cost,"TaxProxy":tax,"Start":str(sim.equity.index.min().date()),"End":str(sim.equity.index.max().date()),"DSR_8Trials":dsr(sim.ret,8)});rows.append(z)
            sim.equity.to_csv(OUT/f"equity_{st}_{exe}_{cost:g}bp_tax{int(tax)}.csv",header=["equity"])
            if exe=="next_close" and cost==11.5 and not tax:
                primary_ret[st]=sim.ret
                yr=sim.equity.resample("YE").last();calendars[st]=yr.pct_change().dropna().rename(st)
    allr=pd.DataFrame(rows);allr.to_csv(OUT/"all_scenarios.csv",index=False)
    primary=allr[(allr.Execution=="next_close")&(allr.CostBps==11.5)&(~allr.TaxProxy)].sort_values(["Sharpe","Calmar"],ascending=False);primary.to_csv(OUT/"primary_comparison.csv",index=False)
    pd.concat(calendars.values(),axis=1).to_csv(OUT/"calendar_returns.csv")
    pbo=cscv_pbo(pd.DataFrame(primary_ret),8)
    boot=pd.DataFrame([{"A":a,"B":b,"P_Sharpe_A_gt_B":bootstrap(primary_ret[a],primary_ret[b])} for a,b in itertools.combinations(STRATEGIES,2)]);boot.to_csv(OUT/"paired_bootstrap.csv",index=False)
    leader=str(primary.iloc[0].Strategy); ranks=[]
    for (exe,cost,tax),g in allr.groupby(["Execution","CostBps","TaxProxy"]):
        q=g.copy();q["rank"]=q.Sharpe.rank(ascending=False,method="min");x=q[q.Strategy==leader].iloc[0];ranks.append({"Execution":exe,"CostBps":cost,"TaxProxy":bool(tax),"LeaderSharpeRank":int(x["rank"]),"LeaderSharpe":float(x.Sharpe),"LeaderMDD":float(x.MDD)})
    rankdf=pd.DataFrame(ranks);rankdf.to_csv(OUT/"leader_robustness.csv",index=False)
    verdict={"methodology_label":"retrospective apples-to-apples historical tournament; NOT untouched forward OOS","common_window":[str(EVAL_START.date()),str(end.date())],"primary":{"execution":"T+1 adjusted close","cost_bps":11.5,"tax":"pre-tax adjusted total-return"},"tax_stress":"15.4% conservative realized-positive-gain proxy; not statutory tax-base-price accounting","pq_split":"historical KOSPI total market cap vs KOSDAQ150 constituent market cap; 60% equity + 40% 214980; 84d; T+1","primary_leader":leader,"leader_robust_top2_all_scenarios":bool((rankdf.LeaderSharpeRank<=2).all()),"leader_mdd_above_minus30_all_scenarios":bool((rankdf.LeaderMDD>=-.30).all()),"cscv":pbo,"promotion_rule":"Historical ranking cannot override the previously frozen v2 promotion failure; v2 remains SHADOW until genuine forward validation passes."}
    (OUT/"verdict.json").write_text(json.dumps(verdict,ensure_ascii=False,indent=2),encoding="utf-8")
    cols=["Strategy","CAGR","AnnualVol","Sharpe","Sortino","MDD","Calmar","AnnualTurnover","WorstRolling1Y","WorstRolling3Y","WorstRolling5Y","2018_2021_CAGR","2018_2021_Sharpe","2022_LATEST_CAGR","2022_LATEST_Sharpe","DSR_8Trials"]
    report="\n".join(["# Unified Head-to-Head Backtest Result","",f"Common window: {EVAL_START.date()} to {end.date()}","","Primary: T+1 adjusted close, 11.5bp per traded notional, pre-tax adjusted total-return price.","",primary[cols].to_markdown(index=False,floatfmt=".4f"),"","## CSCV / PBO","","```json",json.dumps(pbo,indent=2),"```","","## Paired 21d block bootstrap","",boot.to_markdown(index=False,floatfmt=".4f"),"","## Primary-leader robustness","",rankdf.to_markdown(index=False,floatfmt=".4f"),"","## Frozen interpretation","","Retrospective results do not relax the preregistered v2 promotion gate. A historical v2 win remains SHADOW until genuine forward validation passes."])
    (OUT/"FINAL_UNIFIED_RESULT.md").write_text(report,encoding="utf-8");print(report);print("VERDICT_JSON",json.dumps(verdict,ensure_ascii=False))

if __name__=="__main__":main()
