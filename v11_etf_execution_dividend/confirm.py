from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

import frozen_base as base

OUT=Path("v11_etf_execution_dividend/out"); OUT.mkdir(parents=True,exist_ok=True)
BASELINE="143850"; H="449180"; U="379800"; MIX="MIXED_50"
CANDIDATES=["143850","219480","448290","449180","360750","379800"]
base.METADATA=[
    ("143850","TIGER 미국S&P500선물(H)","미래에셋","futures_hedged"),
    ("219480","KODEX 미국S&P500선물(H)","삼성","futures_hedged"),
    ("448290","TIGER 미국S&P500(H)","미래에셋","physical_hedged"),
    ("449180","KODEX 미국S&P500(H)","삼성","physical_hedged"),
    ("360750","TIGER 미국S&P500","미래에셋","physical_unhedged"),
    ("379800","KODEX 미국S&P500","삼성","physical_unhedged"),
    (MIX,"KODEX 미국S&P500(H) + 미국S&P500 50/50","삼성","mixed_hedge_monthly_rebalanced"),
]
base.KNOWN={s:{"name":name,"issuer":iss,"type":typ} for s,name,iss,typ in base.METADATA}
base.SMA=200
base.LAST_COMPLETE_MONTH="2026-09"
base.FIXED=["069500","148070","411060","153130"]
base.COSTS=(10,25,50)
base.EXECUTIONS=("next_open","next_close")
OFFICIAL={
    "449180":[("2026-07-31",40.),("2026-04-30",42.),("2026-01-30",40.),("2025-10-31",38.)],
    "448290":[("2026-07-31",42.),("2026-04-30",40.),("2026-01-30",41.),("2025-10-31",40.)],
}
def download_actual(sym):
    d=yf.download(sym+".KS",start="2010-01-01",end="2026-10-01",auto_adjust=False,actions=True,
                  progress=False,threads=False,timeout=35)
    if isinstance(d.columns,pd.MultiIndex):
        d=d.xs(sym+".KS",level=-1,axis=1) if sym+".KS" in d.columns.get_level_values(-1) else d.xs(sym+".KS",level=0,axis=1)
    if d.empty or not {"Open","Close","Adj Close"}.issubset(d.columns):
        raise RuntimeError("Missing OHLC for "+sym)
    d.index=pd.to_datetime(d.index).tz_localize(None).normalize()
    d=d.sort_index()
    required=d[["Open","Close","Adj Close"]].apply(pd.to_numeric,errors="coerce")
    required["Adj Open"]=required["Open"]*required["Adj Close"]/required["Close"]
    bad=required.isna().any(axis=1) | (required<=0).any(axis=1) | ~np.isfinite(required).all(axis=1)
    bad_dates=required.index[bad]
    print("DATA_QUALITY",sym,"source_rows",len(required),
          "invalid_rows",len(bad_dates),"sample_invalid_dates",
          [str(x.date()) for x in bad_dates[:12]],flush=True)
    if len(bad_dates)>max(1,int(len(required)*.01)):
        raise RuntimeError("More than 1% invalid price bars "+sym)
    if len(bad_dates) and bad_dates.max()>=pd.Timestamp("2022-11-01"):
        raise RuntimeError("Invalid price rows inside common comparison period "+sym)
    required=required.loc[~bad].copy()
    required["Dividends"]=pd.to_numeric(d.get("Dividends",pd.Series(0,index=d.index)),errors="coerce").fillna(0)
    required["Stock Splits"]=pd.to_numeric(d.get("Stock Splits",pd.Series(0,index=d.index)),errors="coerce").fillna(0)
    if len(required)<250:raise RuntimeError("Less than 250 ETF observations "+sym)
    return required

def monthly_hedge_pair(h:pd.DataFrame,u:pd.DataFrame):
    idx=h.index.intersection(u.index)
    h=h.loc[idx];u=u.loc[idx]
    columns=("Close","Adj Close","Adj Open")
    out=pd.DataFrame(index=idx,columns=columns,dtype=float)
    if len(out)<300: raise RuntimeError("hedge combo history insufficient")
    first=idx[0]
    for col in columns:out.loc[first,col]=100.
    anchor_prev=first
    anchor_mix={c:100. for c in columns}
    anchor_ha={c:float(h.loc[first,c if c!="Adj Open" else "Adj Close"]) for c in columns}
    anchor_ua={c:float(u.loc[first,c if c!="Adj Open" else "Adj Close"]) for c in columns}
    prev_month=first.to_period("M")
    for d in idx[1:]:
        m=d.to_period("M")
        if m!=prev_month:
            anchor_prev=idx[idx.get_loc(d)-1]
            anchor_mix={c:float(out.loc[anchor_prev,c if c!="Adj Open" else "Adj Close"]) for c in columns}
            anchor_ha={c:float(h.loc[anchor_prev,c if c!="Adj Open" else "Adj Close"]) for c in columns}
            anchor_ua={c:float(u.loc[anchor_prev,c if c!="Adj Open" else "Adj Close"]) for c in columns}
            prev_month=m
        for c in columns:
            out.loc[d,c]=anchor_mix[c]*(.5*float(h.loc[d,c])/anchor_ha[c] +
                                       .5*float(u.loc[d,c])/anchor_ua[c])
    # Mixed index is a self-financing, 50:50 rebalanced per month sleeve proxy.
    # Real 6-ETF portfolio has different intra-month holdings and traded-notional costs.
    if out.isna().any().any() or (out<=0).any().any():raise RuntimeError("synthetic price invalid")
    return out

def dist_audit(sym,d):
    values=d[d["Dividends"]>0]["Dividends"]
    rows=[]
    for date,amt in OFFICIAL.get(sym,[]):
        dt=pd.Timestamp(date)
        nearby=values.loc[(values.index>=dt-pd.Timedelta(days=4)) &
                          (values.index<=dt+pd.Timedelta(days=4))]
        exact=bool((abs(nearby-amt)<=.5).any())
        rows.append({"symbol":sym,"official_record_date":date,"gross_per_share_KRW":amt,
                     "yahoo_nearest":str(nearby.index[0].date()) if len(nearby) else "",
                     "yahoo_amount":float(nearby.iloc[0]) if len(nearby) else None,
                     "pass":exact})
    return rows

def signal_audit(d, symbols):
    idx=None
    for s in symbols:
        idx=d[s].index if idx is None else idx.intersection(d[s].index)
    ix=pd.DatetimeIndex(idx)
    ends=base.month_ends(ix)
    out=[]
    for sym in symbols:
        raw=d[s].loc[ix,"Close"]; adj=d[s].loc[ix,"Adj Close"]
        mismatches=[]
        for day in ends:
            if ix.get_loc(day)<249:continue
            r=bool(raw.loc[day]>=raw.loc[:day].tail(200).mean())
            a=bool(adj.loc[day]>=adj.loc[:day].tail(200).mean())
            if r!=a:mismatches.append(str(day.date()))
        out.append({"symbol":sym,"raw_adj_signal_mismatch":len(mismatches),
                    "mismatch_dates":mismatches,"KIS_parity":"UNVERIFIED"})
    return out

def calculate_common(data):
    syms=base.FIXED+CANDIDATES[1:]+[MIX]
    idx=None
    for s in syms:
        idx=data[s].index if idx is None else idx.intersection(data[s].index)
    idx=pd.DatetimeIndex(idx).sort_values()
    # month signals require 250 bars, and most recent month complete.
    if len(idx)<500:raise RuntimeError("Insufficient all-candidate shared daily samples")
    common={s:data[s].loc[idx] for s in syms}
    common[BASELINE]=data[BASELINE].loc[idx]
    csv=[]
    result=[]
    for candidate in CANDIDATES+[MIX]:
        cols=list(dict.fromkeys(base.FIXED+[BASELINE,candidate]))
        raw=pd.DataFrame({s:common[s]["Close"] for s in cols})
        adj=pd.DataFrame({s:common[s]["Adj Close"] for s in cols})
        ao=pd.DataFrame({s:common[s]["Adj Open"] for s in cols})
        for exe in ("next_open","next_close"):
            for bp in (10.,25.,50.):
                for who,code in (("baseline",BASELINE),("candidate",candidate)):
                    p,t=base.periods(raw,adj,ao,exe,code) if False else (None,None)
                    # frozen_base.periods is replaced by following per-version actual target weights.
                    sim=run_strategy(raw,adj,ao,exe,code,bp)
                    if sim.empty:raise RuntimeError("no strategy periods")
                    stat=base.stats(sim.rename(columns={"net":"return","cashret":"rf"}))
                    csv.append({"symbol":candidate,"version":who,"execution":exe,"cost_bp":bp,**stat})
        cand=[x for x in csv if x["symbol"]==candidate and x["version"]=="candidate"
              and x["execution"]=="next_open" and x["cost_bp"]==10.][0]
        bench=[x for x in csv if x["symbol"]==candidate and x["version"]=="baseline"
              and x["execution"]=="next_open" and x["cost_bp"]==10.][0]
        result.append({"symbol":candidate,"months":cand["months"],
                       "start":cand["start"],"end":cand["end"],
                       "candidate_cagr":cand["cagr"],"candidate_sharpe":cand["sharpe"],
                       "candidate_mdd":cand["mdd"],"candidate_calmar":cand["calmar"],
                       "baseline_cagr":bench["cagr"],"baseline_sharpe":bench["sharpe"],
                       "delta_cagr":cand["cagr"]-bench["cagr"],
                       "delta_sharpe":cand["sharpe"]-bench["sharpe"],
                       "min36":cand["months"]>=36})
    return pd.DataFrame(csv),result,common

def run_strategy(raw,adj,ao,execution,us,bp):
    # A strict 250-bar history before any signal as in production v1.1.
    idx=raw.index
    ends=[d for d in base.month_ends(idx) if idx.get_loc(d)>=249]
    rebs=[(d,base.next_day(idx,d)) for d in ends]
    rebs=[(d,next_d) for d,next_d in rebs if next_d is not None]
    px=ao if execution=="next_open" else adj
    cur=pd.Series(0.,index=raw.columns);cur["153130"]=1.
    rows=[]
    for i in range(len(rebs)-1):
        signal,exe_date=rebs[i]; _,next_date=rebs[i+1]
        w=pd.Series(0.,index=raw.columns)
        w["153130"]=.10
        for symbol,weight in (("069500",.30),(us,.30),("148070",.15),("411060",.15)):
            h=raw.loc[:signal,symbol].tail(200)
            if len(h)<200:raise RuntimeError("SMA insufficient")
            if float(h.iloc[-1])>=float(h.mean()):w[symbol]+=weight
            else:w["153130"]+=weight
        if not np.isclose(float(w.sum()),1.):raise RuntimeError("weights != 1")
        returns=px.loc[next_date]/px.loc[exe_date]-1
        turnover=float((w-cur).abs().sum())
        cost=turnover*bp/10000.
        gross=float((w*returns).sum())
        net=(1-cost)*(1+gross)-1
        cur=w*(1+returns)/(1+gross)
        rows.append({"date":str(exe_date.date()),"net":net,"cashret":float(returns["153130"]),
                     "turnover":turnover,"cost":cost})
    if not rows:return pd.DataFrame()
    return pd.DataFrame(rows).set_index("date")

def main():
    wanted=list(dict.fromkeys(base.FIXED+CANDIDATES))
    data={}
    for s in wanted:
        data[s]=download_actual(s)
        print("FETCH",s,len(data[s]),data[s].index.min(),data[s].index.max(),flush=True)
    data[MIX]=monthly_hedge_pair(data[H],data[U])
    audits=[v for s in OFFICIAL for v in dist_audit(s,data[s])]
    (OUT/"distribution_audit.json").write_text(json.dumps(audits,ensure_ascii=False,indent=2))
    (OUT/"price_history_manifest.json").write_text(json.dumps(
       [{"symbol":s,"rows":len(d),"start":str(d.index.min().date()),"end":str(d.index.max().date()),
         "dividend_events":int((d["Dividends"]>0).sum()) if "Dividends" in d else None} for s,d in data.items()],
       ensure_ascii=False,indent=2))
    print("DISTRIBUTIONS",json.dumps(audits),flush=True)
    signals=signal_audit(data,[BASELINE,H,"448290",U,"411060"])
    (OUT/"signal_adjusted_vs_raw.json").write_text(json.dumps(signals,ensure_ascii=False,indent=2))
    metrics,results,common=calculate_common(data)
    metrics.to_csv(OUT/"common_cohort_metrics.csv",index=False)
    (OUT/"common_cohort_summary.json").write_text(json.dumps(results,ensure_ascii=False,indent=2))
    dividend_ok=all(v["pass"] for v in audits)
    gates={}
    for r in results:
        cand=r["symbol"]
        m=metrics[(metrics.symbol==cand)]
        def get(who,cost=10.,execu="next_open"):
            return m[(m.version==who)&(m.cost_bp==cost)&(m.execution==execu)].iloc[0]
        a=get("candidate");b=get("baseline")
        checks={"min36":bool(a.months>=36),"sharpe":bool(a.sharpe>b.sharpe),
                "calmar":bool(a.calmar>=b.calmar),
                "mdd":bool(abs(a.mdd)<=1.1*abs(b.mdd)),
                "cost25":bool(get("candidate",25.).sharpe>get("baseline",25.).sharpe),
                "cost50":bool(get("candidate",50.).sharpe>get("baseline",50.).sharpe),
                "next_close":bool(get("candidate",10.,"next_close").sharpe>get("baseline",10.,"next_close").sharpe)}
        gates[cand]={"checks":checks,"historical_pass":all(checks.values()),
                     "dividend_parity_verified":dividend_ok if cand in (H,"448290") else None,
                     "09_10_actual_quote_verified":False,
                     "KIS_SMA_parity_verified":False,
                     "real_promotion":"BLOCKED"}
    (OUT/"gates.json").write_text(json.dumps(gates,ensure_ascii=False,indent=2))
    df=pd.DataFrame(results)
    report=["# v1.1 hedged physical ETF / dividend / 09:10 research","",
      "Historical Yahoo adjusted next-open only; **NOT actual 09:10 execution**.","",
      "200 SMA on raw close, minimum 250 bars, actual 411060 15%, 10/25/50bp.","",
      "## Equal-period full portfolio results",df.to_markdown(index=False,floatfmt=".4f"),"",
      "## Distribution ex-date and amount parity (official record date +/- 4 days)",pd.DataFrame(audits).to_markdown(index=False),"",
      "## Raw-versus-adjusted SMA signal discordance",
      pd.DataFrame([{k:v for k,v in x.items() if k!="mismatch_dates"} for x in signals]).to_markdown(index=False),"",
      "## Research gates",json.dumps(gates,ensure_ascii=False,indent=2),"",
      "## Live price and settlement gates","",
      "- REAL 09:10 executions: UNVERIFIED. No authenticated KIS orderbook/print snapshots from 09:10.",
      "- No arbitrary daily OPEN can be called a 09:10 quote, bid, ask, or fill.",
      "- Separate division of dividend-adjusted Yahoo return and raw KIS price signal. Distribution credits, withholding, accounting timing need KIS account/settlement read-only reconciliation.",
      "- Mixed 50/50 instrument is a monthly-rebalanced synthetic index proxy and does not prove the real 6-ETF execution path; all mixed results SHADOW ONLY.",
      "- Monthly sample MDD is not a full intramonth maximum drawdown.",
      "- Baseline ETF outcome is historical, and this study does not change strategy config.",
      "- 09:10 prospective capture requires authorized KIS GET credentials on GCP or similar. Never run order POST as part of this study."]
    (OUT/"REPORT.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    print(df.to_string(index=False),flush=True)
    print("DIVIDEND_PARITY",dividend_ok,"REAL_PROMOTION_BLOCKED",flush=True)

if __name__=="__main__":
    main()
