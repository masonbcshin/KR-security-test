#!/usr/bin/env python3
"""Preregistered safe-sleeve implementation study for the accepted 60/40 core.

Full-history selection candidates are frozen in PR #1 comment 5383435992:
- zero-yield cash baseline
- KODEX 단기채권PLUS (214980)
- KODEX 단기변동금리부채권액티브 (273140)

KOFR/CD ETFs are post-inception diagnostics only and cannot rescue selection.
Price source is NAVER via FinanceDataReader. Because this is not guaranteed to be
a total-return series, results are explicitly a conservative price-only screen.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import FinanceDataReader as fdr

PREREG_COMMENT_ID = 5383435992
TEST_START = "20180101"
TEST_END = "20260320"
INITIAL_CAPITAL = 100_000_000.0
EQUITY_EXPOSURE = 0.60
SAFE_EXPOSURE = 0.40
BUY_COST = 0.0035
SELL_COST = 0.0055
BASELINE_TOL = 1e-10
FULL_CANDIDATES = {"214980": "KODEX 단기채권PLUS", "273140": "KODEX 단기변동금리부채권액티브"}
DIAGNOSTIC_ONLY = {"423160": "KODEX KOFR금리액티브", "459580": "KODEX CD금리액티브"}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--accepted-artifact-dir", required=True)
    p.add_argument("--risk-budget-artifact-dir", required=True)
    p.add_argument("--output", default="outputs/etf_safe_sleeve")
    return p.parse_args()


def fetch(code: str, start: str, end: str) -> pd.DataFrame:
    x = fdr.DataReader(f"NAVER:{code}", pd.Timestamp(start).strftime("%Y-%m-%d"), pd.Timestamp(end).strftime("%Y-%m-%d")).copy().reset_index()
    if x.empty:
        raise RuntimeError(f"empty price series: {code}")
    if "Date" not in x.columns:
        x = x.rename(columns={x.columns[0]: "Date"})
    x["date"] = pd.to_datetime(x["Date"], errors="coerce").dt.strftime("%Y%m%d")
    x["Close"] = pd.to_numeric(x["Close"], errors="coerce")
    x["Volume"] = pd.to_numeric(x["Volume"], errors="coerce")
    return x.dropna(subset=["date", "Close"]).sort_values("date").drop_duplicates("date")[["date", "Close", "Volume"]]


def load_accepted(root: Path):
    sig = pd.read_csv(root / "cadence_84d" / "signals.csv", dtype={"stock_code": str, "date": str})
    raw = None; vol = None
    for code in ("226490", "229200"):
        x = pd.read_csv(root / f"etf_{code}.csv", dtype={"date": str})
        x = x[(x["date"] >= TEST_START) & (x["date"] <= TEST_END)].copy()
        c = x.set_index("date")[["Close"]].rename(columns={"Close": code})
        v = x.set_index("date")[["Volume"]].rename(columns={"Volume": code})
        raw = c if raw is None else raw.join(c, how="outer")
        vol = v if vol is None else vol.join(v, how="outer")
    return sig, raw.sort_index(), vol.reindex(raw.index).sort_index()


def cash_baseline_reference(root: Path):
    p = root / "comparison.csv"
    x = pd.read_csv(p)
    r = x[np.isclose(pd.to_numeric(x["equity_exposure"]), EQUITY_EXPOSURE)].iloc[0]
    return r.to_dict()


def build_price_panel(eq_raw, eq_vol, safe_code=None):
    raw = eq_raw.copy(); vol = eq_vol.copy()
    if safe_code:
        s = fetch(safe_code, "2017-12-01", TEST_END)
        raw = raw.join(s.set_index("date")[["Close"]].rename(columns={"Close": safe_code}), how="left")
        vol = vol.join(s.set_index("date")[["Volume"]].rename(columns={"Volume": safe_code}), how="left")
    return raw, vol


def simulate(signals, raw, volume, safe_code=None, start=TEST_START):
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
        w = {str(c): float(v) * EQUITY_EXPOSURE for c, v in zip(g["stock_code"], g["target_weight"])}
        if safe_code:
            w[safe_code] = SAFE_EXPOSURE
        by_exec.setdefault(later[0], []).append((str(d), w))

    cash = INITIAL_CAPITAL
    pos = {}
    tx = []
    eq = []

    def equity(d):
        return cash + sum(q * float(mark.at[d, c]) for c, q in pos.items() if c in mark.columns and pd.notna(mark.at[d, c]))

    for d in dates:
        for signal, weights in by_exec.get(d, []):
            eq0 = equity(d); desired = {}
            for c, w in weights.items():
                if c not in raw.columns or not bool(tradable.at[d, c]):
                    if c in pos: desired[c] = pos[c]
                    continue
                p = float(raw.at[d, c])
                q = eq0 * float(w) / p
                if c == safe_code:
                    q = float(np.floor(q))
                desired[c] = q
            allc = set(pos) | set(desired)
            for c in sorted(allc):
                old, new = float(pos.get(c, 0)), float(desired.get(c, 0))
                if new >= old - 1e-12 or c not in tradable.columns or not bool(tradable.at[d, c]):
                    continue
                q = old - new; p = float(raw.at[d, c]); gross = q*p; cost = gross*SELL_COST
                cash += gross-cost
                if new > 1e-12: pos[c] = new
                else: pos.pop(c, None)
                tx.append((signal,d,c,"SELL",q,p,gross,cost))
            buys=[]; need=0.0
            for c in sorted(allc):
                old,new=float(pos.get(c,0)),float(desired.get(c,0))
                if new <= old + 1e-12 or c not in tradable.columns or not bool(tradable.at[d,c]): continue
                p=float(raw.at[d,c]); q=new-old; buys.append((c,old,q,p)); need += q*p*(1+BUY_COST)
            scale=min(1.0,cash/need) if need>0 else 1.0
            for c,old,q,p in buys:
                q *= scale
                if c == safe_code: q = float(np.floor(q))
                if q <= 1e-12: continue
                gross=q*p; cost=gross*BUY_COST; cash -= gross+cost; pos[c]=old+q
                tx.append((signal,d,c,"BUY",q,p,gross,cost))
        eq.append((d,equity(d),cash,len(pos)))
    last=dates[-1]
    for c,q in list(pos.items()):
        if c not in mark.columns or pd.isna(mark.at[last,c]): continue
        p=float(mark.at[last,c]); gross=q*p; cost=gross*SELL_COST; cash += gross-cost
        tx.append((TEST_END,last,c,"SELL_END",q,p,gross,cost))
    if eq: eq[-1]=(last,cash,cash,0)
    txdf=pd.DataFrame(tx,columns=["signal_date","execution_date","stock_code","side","shares","price","gross_notional","cost"])
    eqdf=pd.DataFrame(eq,columns=["date","equity","cash","n_positions"])
    return txdf,eqdf


def metrics(eq,tx):
    e=eq.copy(); e["dt"]=pd.to_datetime(e["date"]); e=e.sort_values("dt"); r=e["equity"].pct_change().fillna(0)
    yrs=max((e["dt"].iloc[-1]-e["dt"].iloc[0]).days/365.25,1/365.25)
    total=e["equity"].iloc[-1]/INITIAL_CAPITAL-1; cagr=(1+total)**(1/yrs)-1
    sd=r.std(ddof=1); sharpe=np.sqrt(252)*r.mean()/sd if sd and np.isfinite(sd) else np.nan
    dd=e["equity"]/e["equity"].cummax()-1; mdd=float(dd.min()); calmar=cagr/abs(mdd) if mdd<0 else np.nan
    return {"total_return":float(total),"cagr":float(cagr),"sharpe":float(sharpe),"max_drawdown":mdd,"calmar":float(calmar),"transaction_cost_krw":float(tx["cost"].sum()) if len(tx) else 0.0,"gross_traded_krw":float(tx["gross_notional"].sum()) if len(tx) else 0.0,"end_equity":float(e["equity"].iloc[-1])}


def worst_5y(eq):
    e=eq.reset_index(drop=True); v=e["equity"].to_numpy(float); w=1260
    if len(v)<=w: return np.nan
    ret=v[w:]/v[:-w]-1
    return float(np.min(ret))


def coverage(code):
    x=fetch(code,"2017-12-01",TEST_END)
    return {"date_min":str(x.date.min()),"date_max":str(x.date.max()),"rows":int(len(x)),"zero_volume_rows":int((x.Volume.fillna(0)<=0).sum()),"max_abs_move":float(x.Close.pct_change().abs().max())}


def main():
    a=parse_args(); accepted=Path(a.accepted_artifact_dir); risk=Path(a.risk_budget_artifact_dir); out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
    signals,eqraw,eqvol=load_accepted(accepted); ref=cash_baseline_reference(risk)
    rows=[]; audits={}
    tx0,eq0=simulate(signals,*build_price_panel(eqraw,eqvol,None),safe_code=None)
    m0=metrics(eq0,tx0); m0["worst_5y_total_return"]=worst_5y(eq0)
    for k in ("cagr","sharpe","max_drawdown","calmar"):
        if abs(float(m0[k])-float(ref[k]))>BASELINE_TOL: raise RuntimeError(f"60/40 baseline reproduction failed {k}: {m0[k]} vs {ref[k]}")
    rows.append({"candidate":"cash_zero","label":"40% zero-yield cash","selection_scope":"full_history",**m0,"pass_all":True})
    eq0.to_csv(out/"equity_cash_zero.csv",index=False); tx0.to_csv(out/"transactions_cash_zero.csv",index=False)

    for code,label in FULL_CANDIDATES.items():
        audits[code]=coverage(code)
        if audits[code]["date_min"]>"20180102" or audits[code]["date_max"]<TEST_END: raise RuntimeError(f"coverage gate failed {code}: {audits[code]}")
        raw,vol=build_price_panel(eqraw,eqvol,code); tx,eq=simulate(signals,raw,vol,code)
        m=metrics(eq,tx); m["worst_5y_total_return"]=worst_5y(eq)
        checks={
            "gate_mdd":m["max_drawdown"]>=m0["max_drawdown"]-.01,
            "gate_sharpe":m["sharpe"]>=m0["sharpe"]-.03,
            "gate_calmar":m["calmar"]>=m0["calmar"]*.90,
            "gate_cagr":m["cagr"]>=m0["cagr"]-.005,
            "gate_worst5y":m["worst_5y_total_return"]>=m0["worst_5y_total_return"]-.02,
            "gate_integrity":audits[code]["max_abs_move"]<.10,
        }
        rows.append({"candidate":code,"label":label,"selection_scope":"full_history",**m,**checks,"pass_all":bool(all(checks.values()))})
        eq.to_csv(out/f"equity_{code}.csv",index=False); tx.to_csv(out/f"transactions_{code}.csv",index=False)

    # Post-inception diagnostics only. Never used for full-history selection.
    for code,label in DIAGNOSTIC_ONLY.items():
        audits[code]=coverage(code); start=max(audits[code]["date_min"],TEST_START)
        raw,vol=build_price_panel(eqraw,eqvol,code); tx,eq=simulate(signals,raw,vol,code,start=start)
        m=metrics(eq,tx) if len(eq)>1 else {}
        rows.append({"candidate":code,"label":label,"selection_scope":"post_inception_diagnostic","diagnostic_start":start,**m,"pass_all":False})
        if len(eq): eq.to_csv(out/f"equity_{code}_diagnostic.csv",index=False)

    df=pd.DataFrame(rows); full=df[(df.selection_scope=="full_history") & (df.candidate!="cash_zero") & (df.pass_all==True)].copy()
    selected=None
    if len(full):
        full=full.sort_values(["max_drawdown","sharpe","calmar","transaction_cost_krw"],ascending=[False,False,False,True])
        selected=str(full.iloc[0].candidate)
    df["selected_full_history"]=df.candidate.eq(selected)
    df.to_csv(out/"comparison.csv",index=False)
    (out/"price_audit.json").write_text(json.dumps(audits,ensure_ascii=False,indent=2),encoding="utf-8")
    result={"prereg_comment_id":PREREG_COMMENT_ID,"selected_full_history":selected,"price_return_limitation":"NAVER Close is not guaranteed total-return adjusted; selection is a conservative price-only implementation screen, not exact after-tax total return.","comparison":df.to_dict("records")}
    (out/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(df.to_string(index=False)); print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
