from __future__ import annotations
import json
import sys
from pathlib import Path
import pandas as pd
import requests

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"fx_hedge_longstudy"))
import run as core

def fred_from_mirror(series_code: str):
    url=f"https://api.db.nomics.world/v22/series/FRED/{series_code}?observations=1"
    r=requests.get(url,timeout=25,headers={"User-Agent":"quant-research/1.0"})
    r.raise_for_status()
    payload=r.json()
    series=payload.get("series",{})
    docs=series.get("docs",[])
    if not docs:raise RuntimeError(f"DBnomics missing FRED series {series_code}: {str(payload)[:160]}")
    obj=docs[0]
    periods=obj.get("period",[])
    values=obj.get("value",[])
    if len(periods)!=len(values) or len(periods)<200:
        raise RuntimeError(f"Malformed/missing FRED mirrored series {series_code}: {len(periods)}")
    s=pd.Series(pd.to_numeric(pd.Series(values),errors="coerce").values,index=pd.to_datetime(periods))
    s=s.dropna().sort_index()
    required=2500 if series_code=="DEXKOUS" else 250
    if len(s)<required or s.index.min()>pd.Timestamp("1997-01-01") or s.index.max()<pd.Timestamp("2026-07-01"):
        raise RuntimeError(f"FRED mirror insufficient range {series_code}: {len(s)} {s.index.min()} {s.index.max()}")
    print("MIRRORED FRED",series_code,"rows",len(s),"start",s.index.min(),"end",s.index.max(),flush=True)
    return s

core.fred=fred_from_mirror
if __name__=="__main__":
    core.main()
