from __future__ import annotations
import io, json, math
from pathlib import Path
from urllib.parse import urlencode
import numpy as np
import pandas as pd
import requests
import yfinance as yf

OUT=Path("fx_hedge_longstudy/out"); OUT.mkdir(parents=True,exist_ok=True)
FIRST=pd.Period("1998-01"); LAST=pd.Period("2026-09")
HEDGES=(0.,.5,1.)
SEED=20261028

def download_spy():
    d=yf.download("SPY",start="1996-01-01",end="2026-10-01",auto_adjust=False,actions=True,progress=False,threads=False,timeout=60)
    if isinstance(d.columns,pd.MultiIndex):
        d=d.xs("SPY",level=-1,axis=1) if "SPY" in d.columns.get_level_values(-1) else d.xs("SPY",level=0,axis=1)
    if "Adj Close" not in d: raise RuntimeError("SPY adjusted close missing")
    s=pd.to_numeric(d["Adj Close"],errors="coerce").dropna()
    s.index=pd.to_datetime(s.index).tz_localize(None).normalize()
    s=s.loc[~s.index.duplicated()].sort_index()
    if len(s)<6500 or s.index.min()>pd.Timestamp("1997-01-01") or (s<=0).any(): raise RuntimeError("SPY coverage invalid")
    return s

def fred(code):
    errors=[]
    for params in ({"id":code,"cosd":"1995-01-01","coed":"2026-09-30"},{"id":code}):
        try:
            url="https://fred.stlouisfed.org/graph/fredgraph.csv?"+urlencode(params)
            r=requests.get(url,timeout=50,headers={"User-Agent":"Mozilla/5.0"})
            r.raise_for_status()
            df=pd.read_csv(io.StringIO(r.text))
            dc="observation_date" if "observation_date" in df else "DATE"
            if code not in df:raise ValueError("FRED series absent")
            s=pd.Series(pd.to_numeric(df[code],errors="coerce").values,index=pd.to_datetime(df[dc])).dropna().sort_index()
            if len(s)<180:raise ValueError("FRED short")
            return s
        except Exception as exc:
            errors.append(type(exc).__name__+":"+str(exc)[:140])
    raise RuntimeError(f"FRED {code} no valid source: {errors}")

def align_daily(spy,fx,kr,us):
    idx=spy.index
    f=fx.reindex(idx,method="ffill")
    fd=pd.Series(fx.index,index=fx.index).reindex(idx,method="ffill")
    lag=(pd.Series(idx,index=idx)-fd).dt.days
    krm=kr.groupby(kr.index.to_period("M")).last()/100
    usm=us.groupby(us.index.to_period("M")).last()/100
    d=pd.DataFrame({"spy":spy,"fx":f,"kr":krm.shift(1).reindex(idx.to_period("M")).to_numpy(),
                    "us":usm.shift(1).reindex(idx.to_period("M")).to_numpy(),"fx_lag":lag},index=idx)
    d=d.loc["1997-01-01":"2026-09-30"].copy()
    if d.index.min()>pd.Timestamp("1997-01-10") or len(d)<7000:raise RuntimeError("Insufficient daily sample")
    if d[["spy","fx","kr","us"]].isna().any().any():
        missing=d.loc[d[["spy","fx","kr","us"]].isna().any(axis=1)]
        raise RuntimeError("Daily gaps: "+str(missing.index[:8].tolist()))
    if (d.fx_lag>4).any():raise RuntimeError("Stale FX >4 calendar days "+str(d.index[d.fx_lag>4][:10].tolist()))
    d["dt"]=d.index.to_series().diff().dt.days.fillna(1).clip(lower=1)
    return d

def monthly_frame(d):
    e=d.groupby(d.index.to_period("M")).tail(1)[["spy","fx","kr","us"]].copy()
    e["date"]=e.index
    e.index=e.index.to_period("M")
    e["elapsed"]=e.date.diff().dt.days
    e["spy_r"]=e.spy.pct_change()
    e["fx_x"]=e.fx/e.fx.shift(1)
    e["fwd"]=(1+e.kr.shift(1)*e.elapsed/365)/(1+e.us.shift(1)*e.elapsed/365)
    e["cash"]=1+e.kr.shift(1)*e.elapsed/365
    e=e.loc[FIRST:LAST]
    if not e.index.equals(pd.period_range(FIRST,LAST,freq="M")):raise RuntimeError("Missing months")
    if e[["spy_r","fx_x","fwd","cash"]].isna().any().any():raise RuntimeError("Missing monthly prices/rates")
    return e

def month_signals(d,annual_hedge_drag=.0025):
    r=d.spy.pct_change().fillna(0.)
    fx_g=d.fx/d.fx.shift(1); fx_g=fx_g.fillna(1.)
    day_frac=d.dt/365.
    fwd_day=(1+d.kr*day_frac)/(1+d.us*day_frac)
    last=d.groupby(d.index.to_period("M")).tail(1).index
    prices={"common":d.spy,0.:d.spy*d.fx}
    for h in (.5,1.):
        gross=(1+r)*fx_g + h*(fwd_day-fx_g) - h*annual_hedge_drag*day_frac
        if (gross<=0).any():raise RuntimeError("daily hedge gross <= 0")
        prices[h]=100*gross.cumprod()
    result={}
    for h,p in prices.items():
        flag=(p>=p.rolling(200,min_periods=200).mean()).loc[last]
        flag.index=flag.index.to_period("M")
        result[h]=flag.astype(bool)
    return result

def simulate(e,h,signal,drag=.0025,basis=0.):
    pos=signal.reindex(e.index-1)
    if pos.isna().any():raise RuntimeError("Missing signal previous month")
    is_on=pos.to_numpy(dtype=bool)
    x=e.fx_x.to_numpy()
    f=e.fwd.to_numpy()+basis*e.elapsed.to_numpy()/365.
    gross_equity=(1+e.spy_r.to_numpy())*x + h*(f-x)-h*drag*e.elapsed.to_numpy()/365.
    gross=np.where(is_on,gross_equity,e.cash.to_numpy())
    if not np.isfinite(gross).all() or (gross<=0).any():raise RuntimeError("Invalid monthly return")
    return pd.DataFrame({"return":gross-1,"cash":e.cash.to_numpy()-1,
                         "on":is_on.astype(int),
                         "carry":np.where(is_on,h*(f-1),0.)},index=e.index)

def stats(f):
    n=len(f); r=f["return"]; rf=f.cash
    eq=(1+r).cumprod()
    exc=r-rf; sd=exc.std(ddof=1)*np.sqrt(12)
    sh=float(exc.mean()*12/sd) if sd>0 else float("nan")
    dn=np.sqrt(np.mean(np.minimum(exc.to_numpy(),0)**2)*12)
    so=float(exc.mean()*12/dn) if dn>0 else float("nan")
    cagr=float(eq.iloc[-1]**(12/n)-1)
    dd=eq/eq.cummax()-1
    md=float(dd.min())
    return {"months":n,"start":str(f.index[0]),"end":str(f.index[-1]),
            "cagr":cagr,"sharpe":sh,"sortino":so,
            "vol":float(r.std(ddof=1)*np.sqrt(12)),"mdd":md,
            "calmar":cagr/abs(md) if md<0 else float("nan"),
            "on_ratio":float(f.on.mean()),"annual_carry":float(f.carry.mean()*12)}

def bootstrap(a,b,nboot=4000):
    aa=a["return"].to_numpy(); bb=b["return"].to_numpy()
    rf=a.cash.to_numpy(); n=len(aa); rng=np.random.default_rng(SEED)
    def sharpe(v,ii):
        e=v[ii]-rf[ii]; sd=e.std(ddof=1)
        return e.mean()/sd if sd>0 else float("nan")
    wins=0
    for _ in range(nboot):
        ii=[]
        while len(ii)<n:
            i=int(rng.integers(0,n))
            ii.extend((i+j)%n for j in range(12))
        ii=np.asarray(ii[:n])
        wins+=bool(sharpe(aa,ii)>sharpe(bb,ii))
    return wins/nboot

REGIMES={"1998-2007":("1998-01","2007-12"),
         "2008-2017":("2008-01","2017-12"),
         "2018-2026":("2018-01","2026-09"),
         "Dotcom":("2000-01","2002-12"),
         "GFC":("2008-01","2009-12"),
         "Covid":("2020-01","2020-12"),
         "2022":("2022-01","2022-12")}

def main():
    spy=download_spy()
    fx=fred("DEXKOUS"); kr=fred("IR3TIB01KRM156N"); us=fred("IR3TIB01USM156N")
    provenance={"SPY":{"n":len(spy),"first":str(spy.index.min().date()),"last":str(spy.index.max().date()),"source":"Yahoo adj close"},
                "DEXKOUS":{"n":len(fx),"first":str(fx.index.min().date()),"last":str(fx.index.max().date()),"source":"FRED"},
                "KRW_3M":{"n":len(kr),"first":str(kr.index.min().date()),"last":str(kr.index.max().date()),"source":"FRED"},
                "USD_3M":{"n":len(us),"first":str(us.index.min().date()),"last":str(us.index.max().date()),"source":"FRED"}}
    (OUT/"PROVENANCE.json").write_text(json.dumps(provenance,indent=2),encoding="utf-8")
    print("SOURCE",json.dumps(provenance),flush=True)
    d=align_daily(spy,fx,kr,us)
    e=monthly_frame(d)
    ss=month_signals(d)
    rows=[]; regime_rows=[]; stress_rows=[]; sims={}
    for mode in ("buyhold","common_sma200","native_sma200"):
        for h in HEDGES:
            sig=(pd.Series(True,index=ss["common"].index) if mode=="buyhold"
                 else ss["common"] if mode=="common_sma200" else ss[h])
            sim=simulate(e,h,sig)
            sims[(mode,h)]=sim
            rows.append({"mode":mode,"hedge":h,**stats(sim)})
            for label,(a,b) in REGIMES.items():
                reg=sim.loc[a:b]
                if len(reg)>=12:
                    regime_rows.append({"mode":mode,"hedge":h,"regime":label,**stats(reg)})
            for drag in (0.,.0025,.01):
                for basis in (-.01,0.,.01):
                    stress_rows.append({"mode":mode,"hedge":h,"hedge_drag":drag,"basis":basis,
                                        **stats(simulate(e,h,sig,drag=drag,basis=basis))})
            sim.to_csv(OUT/f"{mode}_hedge_{int(h*100)}_monthly.csv")
    df=pd.DataFrame(rows); regimes=pd.DataFrame(regime_rows)
    df.to_csv(OUT/"full_metrics.csv",index=False)
    regimes.to_csv(OUT/"regime_metrics.csv",index=False)
    pd.DataFrame(stress_rows).to_csv(OUT/"hedge_cost_basis_stress.csv",index=False)
    pairs=[]
    for mode in ("buyhold","common_sma200","native_sma200"):
        for a,b in ((0.,1.),(.5,1.),(0.,.5)):
            full=bootstrap(sims[(mode,a)],sims[(mode,b)])
            hold=bootstrap(sims[(mode,a)].loc["2018-01":"2026-09"],
                           sims[(mode,b)].loc["2018-01":"2026-09"])
            pairs.append({"mode":mode,"candidate":a,"baseline":b,"resample_full":full,"resample_holdout":hold})
    pd.DataFrame(pairs).to_csv(OUT/"bootstrap.csv",index=False)
    checks={}
    for h in (0.,.5):
        main=df[df["mode"]=="native_sma200"].set_index("hedge")
        hold=regimes[(regimes["mode"]=="native_sma200")&(regimes["regime"]=="2018-2026")].set_index("hedge")
        checks[str(h)]={"full_sharpe":bool(main.loc[h,"sharpe"]>main.loc[1.,"sharpe"]),
                         "full_calmar":bool(main.loc[h,"calmar"]>main.loc[1.,"calmar"]),
                         "full_mdd":bool(abs(main.loc[h,"mdd"])<=1.1*abs(main.loc[1.,"mdd"])),
                         "holdout_sharpe":bool(hold.loc[h,"sharpe"]>hold.loc[1.,"sharpe"]),
                         "holdout_calmar":bool(hold.loc[h,"calmar"]>hold.loc[1.,"calmar"]),
                         "holdout_mdd":bool(abs(hold.loc[h,"mdd"])<=1.1*abs(hold.loc[1.,"mdd"]))}
    decision="NO_ROBUST_HEDGE_POLICY_WINNER"
    (OUT/"VERDICT.json").write_text(json.dumps({"decision":decision,"checks":checks,
       "note":"Structural research only; need actual Korean ETF tracking and live KIS spread verification"},indent=2),encoding="utf-8")
    parts=["# 1998-2026 S&P500 FX Hedge Economic Study","",
           "This is an economic proxy; not actual KIS ETF executions.","",
           "## Source provenance",json.dumps(provenance,indent=2),"",
           "## Long horizon comparison",df.to_markdown(index=False,floatfmt=".4f"),"",
           "## Historical regimes",regimes.to_markdown(index=False,floatfmt=".4f"),"",
           "## Bootstrap resampling",pd.DataFrame(pairs).to_markdown(index=False,floatfmt=".4f"),"",
           "## Policy gates",json.dumps(checks,indent=2),"",
           "## Limitations","SPY is dividend-adjusted, FRED FX close calendar differs from SPY.",
           "Forward rates use previous-month 3m interbank rate and frictionless CIP, with 25bp/year default extra hedge transaction cost.",
           "FRED economic series may be revised; this is not point-in-time data.",
           "200-day SMA per native KRW hedge price differs by FX policy.",
           "Samples are in-sample historical outcomes; 2018-2026 is a frozen retrospective holdout, NOT future market data.",
           "No 28yr KRX gold 411060 portfolio exists; separate actual ETF validation required."]
    (OUT/"REPORT.md").write_text("\n".join(parts)+"\n",encoding="utf-8")
    print(df.to_string(index=False),flush=True)
    print(pd.DataFrame(pairs).to_string(index=False),flush=True)
    print("SUCCESS outputs",flush=True)

if __name__=="__main__":
    main()
