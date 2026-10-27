#!/usr/bin/env python3
"""Read-only Korean ETF 09:10 quote evidence capture. Never sends broker orders.

Runs only with explicit date, outputs whitelisted quote fields and clock metadata.
Do not push output (market-data sharing restrictions); keep local on operator VM.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from datetime import datetime, date, timedelta, time as clocktime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

KST=ZoneInfo("Asia/Seoul")
LIVE="https://openapi.koreainvestment.com:9443"
ENDPOINT="/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
TR_ID="FHKST01010200"
ALLOW=frozenset({"143850","219480","448290","449180","360750","379800","411060"})
def main():
    p=argparse.ArgumentParser(description="GET-only 09:10 ETF orderbook capture")
    p.add_argument("--day",required=True,help="KRX session date YYYY-MM-DD (operator verified)")
    p.add_argument("--symbols",nargs="+",default=["143850","448290","449180","379800","411060"])
    p.add_argument("--out",type=Path,required=True,help="Local JSONL, NEVER commit raw prices")
    args=p.parse_args()
    if any(s not in ALLOW for s in args.symbols) or len(set(args.symbols))!=len(args.symbols):
        p.error("Unapproved symbols or duplicates")
    day=date.fromisoformat(args.day)
    if day.weekday()>4:p.error("Weekend; verify a real KRX session before using")
    now=datetime.now(KST)
    if now.date()!=day:
        p.error("Capture day must be TODAY in Korea, cannot fabricate past/future broker observations")
    key=os.environ.get("KIS_APP_KEY","")
    secret=os.environ.get("KIS_APP_SECRET","")
    token=os.environ.get("KIS_ACCESS_TOKEN","")
    if any(not x for x in (key,secret,token)):
        p.error("KIS_APP_KEY/KIS_APP_SECRET/KIS_ACCESS_TOKEN must be supplied in environment")
    headers={"Content-Type":"application/json","Authorization":"Bearer "+token,
             "appkey":key,"appsecret":secret,"tr_id":TR_ID,"custtype":"P"}
    start=datetime.combine(day,clocktime(9,9,50),KST)
    stop=datetime.combine(day,clocktime(9,10,20),KST)
    if now>stop:p.error("09:10 capture window is already over")
    args.out.parent.mkdir(parents=True,exist_ok=True)
    if args.out.exists():p.error("Refuse overwrite existing evidence file")
    # no stdout/debug request response credential leakage
    with args.out.open("x",encoding="utf-8") as out:
        os.chmod(args.out,0o600)
        session=requests.Session()
        n=0
        while datetime.now(KST)<stop:
            now=datetime.now(KST)
            if now<start:
                time.sleep(min(1.,(start-now).total_seconds()))
                continue
            for sym in args.symbols:
                if datetime.now(KST)>stop:break
                before=datetime.now(KST)
                row={"symbol":sym,"request_started_at":before.isoformat(),"provider":"KIS_GET_REAL",
                     "tr_id":TR_ID,"source_has_explicit_date":False,
                     "order_submitted":False}
                try:
                    response=session.get(
                        LIVE+ENDPOINT,params={"FID_COND_MRKT_DIV_CODE":"J","FID_INPUT_ISCD":sym},
                        headers=headers,timeout=(8,12))
                    after=datetime.now(KST)
                    row["received_at"]=after.isoformat()
                    row["http_status"]=response.status_code
                    if response.ok:
                        body=response.json()
                        row["rt_cd"]=body.get("rt_cd")
                        o=body.get("output1") if isinstance(body.get("output1"),dict) else {}
                        o2=body.get("output2") if isinstance(body.get("output2"),dict) else {}
                        row.update({"source_hhmmss":o.get("aspr_acpt_hour"),
                            "bid1":o.get("bidp1"),"ask1":o.get("askp1"),
                            "bid1_size":o.get("bidp_rsqn1"),"ask1_size":o.get("askp_rsqn1"),
                            "last_trade":o2.get("stck_prpr"),
                            "market_kind":o.get("new_mkop_cls_code")})
                    else:
                        row["error"]="HTTP_NON_SUCCESS_NO_BODY_RECORDED"
                except Exception:
                    row["received_at"]=datetime.now(KST).isoformat()
                    row["error"]="NETWORK_OR_SCHEMA_FAILURE_DETAILS_REDACTED"
                out.write(json.dumps(row,ensure_ascii=False)+"\n")
                out.flush(); n+=1
                time.sleep(.35)
            time.sleep(1.0)
    print(json.dumps({"file":str(args.out),"records":n,"has_actual_order_fill_proof":False,
                      "status":"GET_QUOTE_ONLY", "warning":"source date is not explicitly in KIS REST orderbook"},ensure_ascii=False))
if __name__=="__main__":main()
