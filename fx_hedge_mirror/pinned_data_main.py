from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"fx_hedge_longstudy"))
import run as core

BASE=Path(__file__).resolve().parents[1]/"fx_hedge_inputs"
ALLOWED={"DEXKOUS","IR3TIB01KRM156N","IR3TIB01USM156N"}

def fred_pinned(code: str):
    if code not in ALLOWED:
        raise ValueError(f"Unregistered series: {code}")
    path=BASE/(code+".csv")
    d=pd.read_csv(path)
    if list(d.columns)!=["DATE",code]:
        raise RuntimeError(f"Unexpected FRED source columns {path}")
    t=pd.to_datetime(d["DATE"],errors="raise")
    raw=pd.Series(pd.to_numeric(d[code],errors="coerce").to_numpy(),index=t)
    if code=="IR3TIB01USM156N":
        missing=raw[raw.isna()]
        if list(missing.index.strftime("%Y-%m-%d")) != ["2020-04-01"]:
            raise RuntimeError("Unexpected missing US interbank month: "+str(missing.index.tolist()))
        alt=pd.read_csv(BASE/"FALLBACK_US_2020_04.csv")
        if len(alt)!=1 or alt.loc[0,"date"]!="2020-04-01" or alt.loc[0,"source_series"]!="TB3MS":
            raise RuntimeError("Invalid single-month fallback provenance")
        raw.loc["2020-04-01"]=float(alt.loc[0,"rate_percent"])
        print("US_INTERBANK_MONTH_PROXY 2020-04 FRED TB3MS 0.14% (NOT actual interbank)",flush=True)
    s=raw.dropna().sort_index()
    if not s.index.is_unique:raise RuntimeError(f"Duplicate FRED observations: {code}")
    n=2500 if code=="DEXKOUS" else 350
    if len(s)<n or s.index.min()>pd.Timestamp("1997-01-01") or s.index.max()<pd.Timestamp("2026-09-01"):
        raise RuntimeError(f"FRED pinned series incomplete {code}: {len(s)} {s.index.min()} {s.index.max()}")
    print("FRED verified pin:",code,"count",len(s),"range",s.index.min().date(),s.index.max().date(),flush=True)
    return s

core.fred=fred_pinned
if __name__=="__main__":
    core.main()
