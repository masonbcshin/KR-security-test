#!/usr/bin/env python3
"""Forward-only PAPER execution engine for PQ-CORE-60-40-214980-V1.

This module validates execution mechanics only. It cannot submit brokerage orders.
It consumes a frozen signal/status JSON produced by the target calculator and a
synthetic PAPER state, then records deterministic whole-share fills on exactly T+1.

Safety semantics:
- DATA_READY=false => DATA_NOT_READY / no order
- before T+1 => WAITING_T1 / no order
- after missed T+1 => REPLAY_BLOCKED / no historical fill
- repeated signal_id => NOOP_DUPLICATE / state unchanged
- sells before buys; all three ETFs whole-share; cash cannot go negative
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import FinanceDataReader as fdr
import numpy as np
import pandas as pd

STRATEGY_ID = "PQ-CORE-60-40-214980-V1"
CODES = ["226490", "229200", "214980"]
LABELS = {
    "226490": "KODEX KOSPI",
    "229200": "KODEX KOSDAQ150",
    "214980": "KODEX 단기채권PLUS",
}
EQUITY_CODES = ["226490", "229200"]
DEFENSIVE_CODE = "214980"
EQUITY_EXPOSURE = 0.60
DEFENSIVE_EXPOSURE = 0.40
INITIAL_PAPER_CAPITAL = 100_000_000.0
BUY_COST = 0.0035
SELL_COST = 0.0055
EPS = 1e-9


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--signal-json")
    p.add_argument("--state")
    p.add_argument("--as-of", help="YYYYMMDD")
    p.add_argument("--prices-json", help="optional deterministic fill-price JSON")
    p.add_argument("--output", default="outputs/personal_quant_paper_core")
    p.add_argument("--self-test", action="store_true")
    return p.parse_args()


def canonical_json(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_signal_id(signal_date: str, execution_date: str, weights: dict[str, float]) -> str:
    payload = {
        "strategy_id": STRATEGY_ID,
        "signal_date": str(signal_date),
        "execution_date": str(execution_date),
        "target_weights": {c: round(float(weights[c]), 12) for c in CODES},
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def validate_weights(weights: dict[str, float]):
    if set(weights) != set(CODES):
        raise RuntimeError(f"unexpected target codes: {sorted(weights)}")
    w = {c: float(weights[c]) for c in CODES}
    if not all(np.isfinite(v) and v >= 0 for v in w.values()):
        raise RuntimeError(f"invalid target weights: {w}")
    if abs(sum(w.values()) - 1.0) > 1e-10:
        raise RuntimeError(f"weights do not sum to 1: {w}")
    if abs(w[DEFENSIVE_CODE] - DEFENSIVE_EXPOSURE) > 1e-12:
        raise RuntimeError(f"defensive sleeve drift: {w[DEFENSIVE_CODE]}")
    if abs(sum(w[c] for c in EQUITY_CODES) - EQUITY_EXPOSURE) > 1e-12:
        raise RuntimeError(f"equity sleeve drift: {w}")
    return w


def new_state(capital: float = INITIAL_PAPER_CAPITAL):
    return {
        "strategy_id": STRATEGY_ID,
        "initial_capital_krw": float(capital),
        "cash_krw": float(capital),
        "holdings": {c: 0 for c in CODES},
        "processed_signal_ids": [],
        "ledger": [],
    }


def normalize_state(state: dict | None):
    if not state:
        return new_state()
    x = copy.deepcopy(state)
    if x.get("strategy_id") != STRATEGY_ID:
        raise RuntimeError(f"paper state strategy drift: {x.get('strategy_id')}")
    x.setdefault("initial_capital_krw", INITIAL_PAPER_CAPITAL)
    x.setdefault("cash_krw", float(x["initial_capital_krw"]))
    x.setdefault("holdings", {})
    x["holdings"] = {c: int(x["holdings"].get(c, 0)) for c in CODES}
    if any(q < 0 for q in x["holdings"].values()):
        raise RuntimeError(f"negative holdings in state: {x['holdings']}")
    x.setdefault("processed_signal_ids", [])
    x.setdefault("ledger", [])
    if float(x["cash_krw"]) < -EPS:
        raise RuntimeError("negative cash in input state")
    return x


def load_signal(path: Path):
    s = json.loads(path.read_text(encoding="utf-8"))
    if s.get("strategy_id") != STRATEGY_ID:
        raise RuntimeError(f"signal strategy drift: {s.get('strategy_id')}")
    weights = validate_weights(s["target_weights"])
    signal_date = str(s["latest_scheduled_signal"])
    execution_date = s.get("signal_execution_date")
    if not execution_date:
        raise RuntimeError("signal_execution_date missing")
    execution_date = str(execution_date)
    signal_id = canonical_signal_id(signal_date, execution_date, weights)
    return {
        "strategy_id": STRATEGY_ID,
        "signal_date": signal_date,
        "execution_date": execution_date,
        "target_weights": weights,
        "signal_id": signal_id,
        "data_ready": bool(s.get("DATA_READY", s.get("LIVE_READY", False))),
        "blocking_reason": s.get("blocking_reason"),
        "source_status": s,
    }


def fetch_execution_closes(as_of: str):
    start = (pd.Timestamp(as_of) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    end = pd.Timestamp(as_of).strftime("%Y-%m-%d")
    out = {}
    for code in CODES:
        x = fdr.DataReader(f"NAVER:{code}", start, end).copy().reset_index()
        if x.empty:
            raise RuntimeError(f"empty execution price source: {code}")
        if "Date" not in x.columns:
            x = x.rename(columns={x.columns[0]: "Date"})
        x["date"] = pd.to_datetime(x["Date"], errors="coerce").dt.strftime("%Y%m%d")
        x["Close"] = pd.to_numeric(x["Close"], errors="coerce")
        x["Volume"] = pd.to_numeric(x["Volume"], errors="coerce")
        x = x[
            (x["date"] == as_of)
            & np.isfinite(x["Close"])
            & (x["Close"] > 0)
            & (x["Volume"].fillna(0) > 0)
        ]
        if x.empty:
            raise RuntimeError(f"same-day tradable execution close missing: {code} @ {as_of}")
        out[code] = float(x.iloc[-1]["Close"])
    return out


def validate_prices(prices: dict[str, float]):
    if set(prices) != set(CODES):
        raise RuntimeError(f"unexpected price codes: {sorted(prices)}")
    p = {c: float(prices[c]) for c in CODES}
    if not all(np.isfinite(v) and v > 0 for v in p.values()):
        raise RuntimeError(f"invalid fill prices: {p}")
    return p


def marked_equity(state: dict, prices: dict[str, float]):
    return float(state["cash_krw"]) + sum(int(state["holdings"][c]) * float(prices[c]) for c in CODES)


def _desired_shares(equity: float, weights: dict[str, float], prices: dict[str, float]):
    return {c: int(np.floor(float(equity) * float(weights[c]) / float(prices[c]))) for c in CODES}


def _fit_buys_to_cash(deltas: dict[str, int], prices: dict[str, float], cash: float):
    """Deterministically fit positive deltas to cash without creating negative cash."""
    buys = {c: max(0, int(deltas.get(c, 0))) for c in CODES}
    required = sum(q * prices[c] * (1.0 + BUY_COST) for c, q in buys.items())
    if required <= cash + EPS:
        return buys

    scale = max(0.0, cash / required) if required > 0 else 0.0
    fitted = {c: int(np.floor(q * scale)) for c, q in buys.items()}
    spent = sum(q * prices[c] * (1.0 + BUY_COST) for c, q in fitted.items())
    remaining = cash - spent

    # Use remaining cash one share at a time for the most under-filled target.
    while True:
        candidates = []
        for c in CODES:
            if fitted[c] >= buys[c]:
                continue
            one = prices[c] * (1.0 + BUY_COST)
            if one <= remaining + EPS:
                deficit_ratio = (buys[c] - fitted[c]) / max(buys[c], 1)
                candidates.append((deficit_ratio, -prices[c], c, one))
        if not candidates:
            break
        candidates.sort(reverse=True)
        _, _, c, one = candidates[0]
        fitted[c] += 1
        remaining -= one
    return fitted


def execute_once(state: dict, signal: dict, prices: dict[str, float], as_of: str):
    before = normalize_state(state)
    sid = signal["signal_id"]

    if sid in before["processed_signal_ids"]:
        return {
            "status": "NOOP_DUPLICATE",
            "signal_id": sid,
            "orders": [],
            "state": before,
        }
    if not signal["data_ready"]:
        return {
            "status": "DATA_NOT_READY",
            "signal_id": sid,
            "blocking_reason": signal.get("blocking_reason"),
            "orders": [],
            "state": before,
        }
    if as_of < signal["execution_date"]:
        return {
            "status": "WAITING_T1",
            "signal_id": sid,
            "orders": [],
            "state": before,
        }
    if as_of > signal["execution_date"]:
        return {
            "status": "REPLAY_BLOCKED",
            "signal_id": sid,
            "orders": [],
            "state": before,
        }

    prices = validate_prices(prices)
    after = copy.deepcopy(before)
    equity0 = marked_equity(before, prices)
    desired = _desired_shares(equity0, signal["target_weights"], prices)
    current = {c: int(before["holdings"][c]) for c in CODES}
    deltas = {c: desired[c] - current[c] for c in CODES}
    orders = []

    # Sell first.
    for c in CODES:
        q = max(0, -deltas[c])
        if q <= 0:
            continue
        gross = q * prices[c]
        cost = gross * SELL_COST
        after["cash_krw"] += gross - cost
        after["holdings"][c] -= q
        orders.append({
            "stock_code": c,
            "label": LABELS[c],
            "side": "SELL",
            "shares": q,
            "price": prices[c],
            "gross_notional": gross,
            "modeled_cost": cost,
        })

    buy_deltas = {c: max(0, deltas[c]) for c in CODES}
    fitted = _fit_buys_to_cash(buy_deltas, prices, float(after["cash_krw"]))
    for c in CODES:
        q = int(fitted[c])
        if q <= 0:
            continue
        gross = q * prices[c]
        cost = gross * BUY_COST
        total = gross + cost
        if total > float(after["cash_krw"]) + EPS:
            raise RuntimeError(f"cash safety invariant failed on {c}")
        after["cash_krw"] -= total
        after["holdings"][c] += q
        orders.append({
            "stock_code": c,
            "label": LABELS[c],
            "side": "BUY",
            "shares": q,
            "price": prices[c],
            "gross_notional": gross,
            "modeled_cost": cost,
        })

    if float(after["cash_krw"]) < -EPS:
        raise RuntimeError(f"negative cash after execution: {after['cash_krw']}")
    after["cash_krw"] = max(0.0, float(after["cash_krw"]))
    after["processed_signal_ids"].append(sid)
    ledger_entry = {
        "signal_id": sid,
        "signal_date": signal["signal_date"],
        "execution_date": signal["execution_date"],
        "filled_as_of": as_of,
        "target_weights": signal["target_weights"],
        "fill_prices": prices,
        "equity_before_costs": equity0,
        "orders": orders,
        "cash_after": after["cash_krw"],
        "holdings_after": copy.deepcopy(after["holdings"]),
    }
    after["ledger"].append(ledger_entry)
    equity_after = marked_equity(after, prices)
    return {
        "status": "PAPER_FILLED",
        "signal_id": sid,
        "orders": orders,
        "equity_before_costs": equity0,
        "equity_after_fill": equity_after,
        "state": after,
    }


def _synthetic_signal(data_ready=True):
    weights = {"226490": 0.54, "229200": 0.06, "214980": 0.40}
    signal_date = "20261127"
    execution_date = "20261130"
    return {
        "strategy_id": STRATEGY_ID,
        "signal_date": signal_date,
        "execution_date": execution_date,
        "target_weights": validate_weights(weights),
        "signal_id": canonical_signal_id(signal_date, execution_date, weights),
        "data_ready": bool(data_ready),
        "blocking_reason": None if data_ready else ["synthetic stale data"],
    }


def self_test():
    prices = {"226490": 70000.0, "229200": 15000.0, "214980": 110000.0}
    s = _synthetic_signal(True)
    base = new_state()

    assert abs(sum(s["target_weights"].values()) - 1.0) < 1e-12
    assert abs(s["target_weights"][DEFENSIVE_CODE] - 0.40) < 1e-12
    assert abs(sum(s["target_weights"][c] for c in EQUITY_CODES) - 0.60) < 1e-12

    stale = execute_once(base, _synthetic_signal(False), prices, "20261130")
    assert stale["status"] == "DATA_NOT_READY" and stale["state"] == base

    early = execute_once(base, s, prices, "20261127")
    assert early["status"] == "WAITING_T1" and early["state"] == base

    late = execute_once(base, s, prices, "20261201")
    assert late["status"] == "REPLAY_BLOCKED" and late["state"] == base

    filled = execute_once(base, s, prices, "20261130")
    assert filled["status"] == "PAPER_FILLED"
    assert filled["state"]["cash_krw"] >= -EPS
    assert all(int(filled["state"]["holdings"][c]) >= 0 for c in CODES)
    assert len(filled["state"]["processed_signal_ids"]) == 1

    snap = copy.deepcopy(filled["state"])
    dup = execute_once(snap, s, prices, "20261130")
    assert dup["status"] == "NOOP_DUPLICATE"
    assert dup["state"] == snap

    print("paper_core_self_test=PASS")
    print(json.dumps({
        "strategy_id": STRATEGY_ID,
        "filled_orders": filled["orders"],
        "cash_after": filled["state"]["cash_krw"],
        "holdings_after": filled["state"]["holdings"],
    }, ensure_ascii=False, indent=2))


def main():
    a = parse_args()
    if a.self_test:
        self_test()
        return
    if not a.signal_json or not a.as_of:
        raise ValueError("--signal-json and --as-of are required unless --self-test")

    signal = load_signal(Path(a.signal_json))
    state = new_state()
    if a.state:
        state = normalize_state(json.loads(Path(a.state).read_text(encoding="utf-8")))

    prices = None
    if a.as_of == signal["execution_date"] and signal["data_ready"] and signal["signal_id"] not in state["processed_signal_ids"]:
        if a.prices_json:
            prices = validate_prices(json.loads(Path(a.prices_json).read_text(encoding="utf-8")))
        else:
            prices = fetch_execution_closes(a.as_of)
    elif a.prices_json:
        prices = validate_prices(json.loads(Path(a.prices_json).read_text(encoding="utf-8")))
    else:
        # Not needed for blocked/waiting/duplicate paths.
        prices = {c: 1.0 for c in CODES}

    result = execute_once(state, signal, prices, a.as_of)
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "paper_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "paper_state.json").write_text(
        json.dumps(result["state"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if result.get("orders"):
        pd.DataFrame(result["orders"]).to_csv(out / "paper_orders.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
