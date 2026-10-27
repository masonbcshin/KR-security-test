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
    s=pd.Series(pd.to_numeric(d[code],errors="coerce").to_numpy(),index=t).dropna().sort_index()
    if not s.index.is_unique:raise RuntimeError(f"Duplicate FRED observations: {code}")
    n=2500 if code=="DEXKOUS" else 350
    if len(s)<n or s.index.min()>pd.Timestamp("1997-01-01") or s.index.max()<pd.Timestamp("2026-09-01"):
        raise RuntimeError(f"FRED pinned series incomplete {code}: {len(s)} {s.index.min()} {s.index.max()}")
    print("FRED verified pin:",code,"count",len(s),"range",s.index.min().date(),s.index.max().date(),flush=True)
    return s

core.fred=fred_pinned
if __name__=="__main__":
    core.main()
