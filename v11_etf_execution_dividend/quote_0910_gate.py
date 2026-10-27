"""Read-only 09:10 execution evidence gate. Never connects to broker or submits orders.

A separate authorized collector must capture time-stamped GET quote / orderbook at source.
This parser NEVER infers a fill from a daily open or minute-close.
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

KST=ZoneInfo("Asia/Seoul")
ALLOWED={"069500","143850","219480","448290","449180","360750","379800","148070","411060","153130"}
BAD={"SECRET","TOKEN","APPKEY","APPSECRET","AUTHORIZATION","ACCOUNT","PASS","CUSTTYPE"}

def inspect(rows: list[dict], symbol: str, *, min_depth: int=1) -> dict:
    evidence=[]
    for o in rows:
        if o.get("symbol")!=symbol:continue
        if set(k.upper() for k in o.keys()) & BAD:
            raise ValueError("Snapshot contains credential or account-related fields")
        try:
            observed=datetime.fromisoformat(str(o["broker_event_time"]))
            captured=datetime.fromisoformat(str(o["received_at"]))
            bid=Decimal(str(o["bid1"])); ask=Decimal(str(o["ask1"]))
            bv=int(o["bid1_size"]); av=int(o["ask1_size"])
            last=Decimal(str(o["last_trade"]))
            if observed.tzinfo is None or captured.tzinfo is None:raise ValueError("Timezone required")
            observed=observed.astimezone(KST); captured=captured.astimezone(KST)
            if observed.date()!=captured.date():raise ValueError("Session day mismatch")
            if not (time(9,9,55)<=observed.time()<=time(9,10,5)):
                continue
            lag=(captured-observed).total_seconds()
            if lag < 0 or lag>5:raise ValueError("Quote timestamp lag unacceptable")
            if not (0<bid<=last<=ask and ask>0 and bv>=min_depth and av>=min_depth):
                raise ValueError("Incomplete 2-way depth or crossed market")
            spread=float((ask-bid)/((ask+bid)/2)*10000)
            evidence.append({"timestamp":observed.isoformat(),"bid":str(bid),"ask":str(ask),
                             "bid1_size":bv,"ask1_size":av,"spread_bp":spread,
                             "assumed_buy_worst_ask":str(ask),"assumed_sell_worst_bid":str(bid)})
        except (KeyError,ValueError,TypeError,ArithmeticError) as exc:
            return {"symbol":symbol,"gate":"FAILED_INVALID_EVIDENCE","reason":str(exc)[:150],
                    "observations":len(evidence),"is_actual_fill_proven":False}
    if not evidence:
        return {"symbol":symbol,"gate":"UNVERIFIED_NO_AUTHENTICATED_0910_QUOTE",
                "observations":0,"is_actual_fill_proven":False}
    return {"symbol":symbol,"gate":"QUOTE_SPREAD_OBSERVED_ONLY",
            "observations":len(evidence),"is_actual_fill_proven":False,
            "min_spread_bp":min(x["spread_bp"] for x in evidence),
            "median_spread_bp":sorted(x["spread_bp"] for x in evidence)[len(evidence)//2],
            "snapshots":evidence}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    rows=[json.loads(s) for s in args.input.read_text().splitlines() if s.strip()]
    results=[inspect(rows,s) for s in sorted(ALLOWED)]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2))
    print(json.dumps([{"symbol":x["symbol"],"gate":x["gate"]} for x in results]))
if __name__=="__main__":main()
