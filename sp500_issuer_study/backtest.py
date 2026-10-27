from __future__ import annotations

import json
import math
import traceback
from pathlib import Path
from collections import Counter

import numpy as np
import pandas as pd
import yfinance as yf

OUT = Path("sp500_issuer_study/out")
OUT.mkdir(parents=True, exist_ok=True)
START = "2010-01-01"
LAST_COMPLETE_MONTH = "2026-09"
BASELINE = "143850"
CASH = "153130"
GOLD = "411060"
SMA = 200
COSTS = (10, 25, 50)
EXECUTIONS = ("next_open", "next_close")
SEED = 20261027
METADATA = [
    ("143850", "TIGER 미국S&P500선물(H)", "미래에셋", "futures_hedged"),
    ("219480", "KODEX 미국S&P500선물(H)", "삼성", "futures_hedged"),
    ("448290", "TIGER 미국S&P500(H)", "미래에셋", "physical_hedged"),
    ("449180", "KODEX 미국S&P500(H)", "삼성", "physical_hedged"),
    ("453330", "RISE 미국S&P500(H)", "KB", "physical_hedged"),
    ("449780", "KIWOOM 미국S&P500(H)", "키움", "physical_hedged"),
    ("269540", "PLUS 미국S&P500(H)", "한화", "physical_hedged"),
    ("360750", "TIGER 미국S&P500", "미래에셋", "physical_unhedged"),
    ("379800", "KODEX 미국S&P500", "삼성", "physical_unhedged"),
    ("360200", "ACE 미국S&P500", "한국투자", "physical_unhedged"),
    ("379780", "RISE 미국S&P500", "KB", "physical_unhedged"),
    ("433330", "SOL 미국S&P500", "신한", "physical_unhedged"),
    ("444490", "WON 미국S&P500", "우리", "physical_unhedged"),
    ("449770", "KIWOOM 미국S&P500", "키움", "physical_unhedged"),
    ("429760", "PLUS 미국S&P500", "한화", "physical_unhedged"),
    ("432840", "HANARO 미국S&P500", "NH아문디", "physical_unhedged"),
    ("0026S0", "1Q 미국S&P500", "하나", "physical_unhedged"),
]
FIXED = ["069500", "148070", "411060", CASH]
WEIGHTS = {"069500": 0.30, "US": 0.30, "148070": 0.15, GOLD: 0.15}
KNOWN = {k: {"name": name, "issuer": issuer, "type": typ} for k,name,issuer,typ in METADATA}


def load(symbol: str):
    ticker = symbol + ".KS"
    errors = []
    for attempt in range(2):
        try:
            d = yf.download(ticker, start=START, end="2026-10-28", auto_adjust=False,
                            actions=True, progress=False, threads=False, timeout=32)
            if isinstance(d.columns, pd.MultiIndex):
                if ticker in d.columns.get_level_values(-1):
                    d = d.xs(ticker, level=-1, axis=1)
                elif ticker in d.columns.get_level_values(0):
                    d = d.xs(ticker, level=0, axis=1)
            if d.empty or not {"Open", "Close", "Adj Close"}.issubset(d.columns):
                raise ValueError("Yahoo missing full adjusted OHLC " + str(list(d.columns)))
            d = d[["Open", "Close", "Adj Close"]].copy()
            d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
            d = d.apply(pd.to_numeric, errors="coerce").dropna()
            d = d[~d.index.duplicated(keep="last")].sort_index()
            d["Adj Open"] = d["Open"] * d["Adj Close"] / d["Close"]
            d = d.replace([np.inf, -np.inf], np.nan).dropna()
            if (d[["Open","Close","Adj Close","Adj Open"]] <= 0).any().any():
                raise ValueError("non-positive price")
            if len(d) < 201:
                raise ValueError("insufficient warmup rows " + str(len(d)))
            return d, None
        except Exception as e:
            errors.append(type(e).__name__ + ": " + str(e)[:230])
    return None, " | ".join(errors)


def month_ends(index):
    s = pd.Series(index, index=index)
    return [pd.Timestamp(x) for x in s.groupby(index.to_period("M")).last().tolist()
            if pd.Timestamp(x).to_period("M") <= pd.Period(LAST_COMPLETE_MONTH)]


def next_day(index, date):
    i = index.searchsorted(date, side="right")
    return index[i] if i < len(index) else None


def simulate(raw, adj, adj_open, us, cost_bp, execution):
    # Shared dates for benchmark and challenger; no forward-filled prices.
    idx = raw.index
    months = [d for d in month_ends(idx) if idx.get_loc(d) >= SMA - 1]
    events = [(d, next_day(idx,d)) for d in months]
    events = [(d,rd) for d,rd in events if rd is not None]
    px = adj_open if execution == "next_open" else adj
    assets = list(raw.columns)
    cur = pd.Series(0.0, index=assets); cur[CASH] = 1.0
    rows = []
    for i in range(len(events)-1):
        signal, rd = events[i]
        next_rd = events[i+1][1]
        if next_rd is None: continue
        w = pd.Series(0.0, index=assets)
        w[CASH] = 0.10
        for sym, weight in (("069500", .30), (us, .30), ("148070", .15), (GOLD, .15)):
            hist = raw.loc[:signal, sym].tail(SMA)
            if len(hist) < SMA: raise ValueError("SMA history insufficient")
            if float(hist.iloc[-1]) >= float(hist.mean()):
                w[sym] += weight
            else:
                w[CASH] += weight
        assert abs(w.sum()-1.0)<1e-8
        period_return = px.loc[next_rd] / px.loc[rd] - 1.0
        turnover = float((w-cur).abs().sum())
        gross = float((w * period_return).sum())
        cost = turnover * cost_bp / 10000.0
        net = (1.0-cost)*(1.0+gross)-1.0
        cur = w*(1.0+period_return)/(1.0+gross)
        rows.append(dict(date=str(rd.date()), signal_date=str(signal.date()), net=net,
                         rf=float(period_return[CASH]), turnover=turnover, cost=cost,
                         us_weight=float(w[us]), gold_weight=float(w[GOLD])))
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


def summary(sim):
    r = sim.net; rf=sim.rf; n=len(r)
    eq = (1+r).cumprod()
    cagr = float(eq.iloc[-1]**(12.0/n)-1)
    exc = r-rf; vol=float(exc.std(ddof=1)*math.sqrt(12))
    sharpe = float(exc.mean()*12/vol) if vol>0 else float("nan")
    dd = eq / eq.cummax()-1
    mdd = float(dd.min())
    return dict(months=n, start=sim.index[0], end=sim.index[-1], cagr=cagr, sharpe=sharpe,
                mdd=mdd, calmar=cagr/abs(mdd) if mdd<0 else float("nan"),
                annual_turnover=float(sim.turnover.sum()/(n/12)),
                total_cost=float(sim.cost.sum()))


def paired_bootstrap(chall, base, block=12, nboot=3000):
    a=chall.net.to_numpy(); b=base.net.to_numpy(); rf=base.rf.to_numpy()
    n=len(a); rng=np.random.default_rng(SEED)
    def sh(r,idx):
        v=r[idx]-rf[idx]; s=v.std(ddof=1)
        return v.mean()/s if s>0 else float("nan")
    win=0
    for _ in range(nboot):
        sel=[]
        while len(sel)<n:
            start=int(rng.integers(0,n))
            sel.extend((start+j)%n for j in range(block))
        ii=np.asarray(sel[:n],dtype=int)
        win+=bool(sh(a,ii)>sh(b,ii))
    return win/nboot


def pair(data, candidate):
    syms=list(dict.fromkeys(FIXED+[BASELINE,candidate]))
    index=None
    for s in syms:
        index=data[s].index if index is None else index.intersection(data[s].index)
    idx=pd.DatetimeIndex(index).sort_values()
    if len(idx)<300: raise ValueError(f"aligned days={len(idx)} (<300)")
    raw=pd.DataFrame({s:data[s].loc[idx,"Close"] for s in syms})
    adj=pd.DataFrame({s:data[s].loc[idx,"Adj Close"] for s in syms})
    aopen=pd.DataFrame({s:data[s].loc[idx,"Adj Open"] for s in syms})
    res={}; metrics=[]
    for execution in EXECUTIONS:
        for bp in COSTS:
            for label,us in (("baseline",BASELINE),("challenger",candidate)):
                sim=simulate(raw,adj,aopen,us,bp,execution)
                if len(sim)<3: raise ValueError(f"complete monthly periods={len(sim)} (<3)")
                res[label,bp,execution]=sim
                metrics.append(dict(symbol=candidate, version=label,cost_bp=bp,execution=execution,
                                    **summary(sim)))
    chk={key:res["challenger",key[0],key[1]].index.equals(res["baseline",key[0],key[1]].index)
         for key in [(10,"next_open"),(25,"next_open"),(50,"next_open"),(10,"next_close")]}
    assert all(chk.values())
    a=summary(res["challenger",10,"next_open"]);b=summary(res["baseline",10,"next_open"])
    prob=paired_bootstrap(res["challenger",10,"next_open"],res["baseline",10,"next_open"])
    def sh(label,bp,exe):
        return summary(res[label,bp,exe])["sharpe"]
    gates={
       "min_36_months":a["months"]>=36,
       "primary_sharpe":a["sharpe"]>b["sharpe"],
       "calmar":a["calmar"]>b["calmar"],
       "mdd":abs(a["mdd"])<=1.10*abs(b["mdd"]),
       "25bp":sh("challenger",25,"next_open")>sh("baseline",25,"next_open"),
       "50bp":sh("challenger",50,"next_open")>sh("baseline",50,"next_open"),
       "next_close":sh("challenger",10,"next_close")>sh("baseline",10,"next_close"),
       "bootstrap":prob>=.70}
    verdict="RESEARCH_CANDIDATE_ONLY" if all(gates.values()) else "NOT_VALIDATED_OR_TOO_SHORT"
    return metrics,dict(symbol=candidate,**KNOWN[candidate],**a,
                baseline_sharpe=b["sharpe"],baseline_cagr=b["cagr"],
                baseline_mdd=b["mdd"],baseline_calmar=b["calmar"],
                delta_sharpe=a["sharpe"]-b["sharpe"],delta_cagr=a["cagr"]-b["cagr"],
                bootstrap_win_fraction=prob,gates=gates,gate_count=sum(gates.values()),
                decision=verdict)


def main():
    data={}; checks=[]
    symbols=list(dict.fromkeys(FIXED+[x[0] for x in METADATA]))
    for i,s in enumerate(symbols):
        d,e=load(s)
        if d is not None:
            data[s]=d
            checks.append(dict(symbol=s,status="OK",rows=len(d),start=str(d.index[0].date()),
                               end=str(d.index[-1].date()),source="Yahoo adjusted"))
        else:
            checks.append(dict(symbol=s,status="NO_DATA",rows=0,error=e,source="Yahoo"))
        print(i+1,len(symbols),s,checks[-1]["status"],flush=True)
    (OUT/"data_quality.json").write_text(json.dumps(checks,indent=2,ensure_ascii=False),encoding="utf-8")
    missing=[s for s in FIXED+[BASELINE] if s not in data]
    if missing:
        raise RuntimeError("FIXED / BASELINE missing; cannot compare safely: "+str(missing))
    metrics=[]; verdicts=[]
    for s,name,issuer,typ in METADATA:
        if s not in data:
            verdicts.append(dict(symbol=s,name=name,issuer=issuer,type=typ,decision="NO_DATA"));continue
        try:
            m,v=pair(data,s)
            metrics.extend(m)
            verdicts.append(v)
            print("RESULT",s,name,v["months"],v["cagr"],v["sharpe"],v["bootstrap_win_fraction"],v["decision"],flush=True)
        except Exception as e:
            verdicts.append(dict(symbol=s,name=name,issuer=issuer,type=typ,
                                 decision="INVALID_SHORT_OR_ERROR",error=str(e)))
            print("ERROR",s,str(e),flush=True)
    df=pd.DataFrame(metrics); df.to_csv(OUT/"paired_metrics.csv",index=False)
    pd.DataFrame([{k:v for k,v in x.items() if k!="gates"} for x in verdicts]).to_csv(OUT/"candidates.csv",index=False)
    (OUT/"verdicts.json").write_text(json.dumps(verdicts,indent=2,ensure_ascii=False,allow_nan=False),encoding="utf-8")
    quality={x["symbol"]:x for x in checks}
    valid=[v for v in verdicts if "months" in v]
    supported=[v for v in valid if v["decision"]=="RESEARCH_CANDIDATE_ONLY"]
    report=["# Full Korean S&P500 issuer ablation — actual ETF backtest","",
      "IMPORTANT: Different inception dates -> paired baseline per candidate, **not comparable cross-period rankings**.","",
      "Benchmark gold is 411060 KRX spot; only U.S. 30% fund changes; monthly SMA200.", "",
      "Full calendar months through 2026-09; 10/25/50bp, next adjusted open/close, 3,000 resamples.", "",
      "## Data status", "",
      pd.DataFrame(checks)[["symbol","status","rows","start","end"]].to_markdown(index=False) if checks else "",
      "", "## Pairwise candidate vs 143850 on exact matched windows (10bp next_open)", ""]
    if valid:
        z=pd.DataFrame([{k:v.get(k) for k in ("symbol","name","issuer","type","months","cagr","sharpe","mdd","calmar","baseline_sharpe","delta_sharpe","delta_cagr","bootstrap_win_fraction","decision")} for v in valid])
        report.append(z.to_markdown(index=False,floatfmt=".4f"))
    else:report.append("NO VALID CANDIDATES")
    report.extend(["","## Pre-registered gates","",
        *[f"- {v['symbol']} {v.get('name','')}: {v['decision']} "+(str(v.get("gates",v.get("error","")))[:240]) for v in verdicts],
        "","## Important limits","",
        "- Fund price history lengths differ. Fund-class and issuer superiority are NOT inferred from unequal periods.",
        "- Adjusted OHLC is a proxy; KIS 09:10 spread, iNAV and actual fills require forward SHADOW.",
        "- A product that wins one of 17 exploratory comparisons is not an unbiased winner; no automatic REAL promotion.",
        "- Zero or incomplete Yahoo adjusted data are reported explicitly and not substituted with raw closing prices.",
        "- ETF distributions and Yahoo split adjustments must be audited before implementation.","",
        f"Eligible research candidates: {len(supported)} of {len(valid)} valid pairs."])
    (OUT/"REPORT.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    print("\n".join(report[-8:]),flush=True)


if __name__=="__main__":
    main()
