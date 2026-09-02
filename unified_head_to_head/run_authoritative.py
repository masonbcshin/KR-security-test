#!/usr/bin/env python3
from __future__ import annotations

import pandas as pd
import run_unified as u

END = pd.Timestamp("2026-03-20")
SIGNALS = u.HERE / "pq_84d_authoritative_signals.csv"

_original_download_prices = u.download_prices


def download_prices_capped():
    op, cl = _original_download_prices()
    op, cl = op.loc[:END].copy(), cl.loc[:END].copy()
    if op.empty or cl.empty or op.index.max() != cl.index.max():
        raise RuntimeError("Capped price panel is invalid")
    op.to_csv(u.OUT / "adjusted_open.csv")
    cl.to_csv(u.OUT / "adjusted_close.csv")
    return op, cl


def pq_targets_authoritative(index):
    df = pd.read_csv(SIGNALS, dtype={"stock_code": str})
    df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d")
    df = df[df["date"] <= END].copy()
    out = {}
    for sd, g in df.groupby("date", sort=True):
        ed = u.next_day(index, sd)
        if ed is None or ed > END:
            continue
        m = dict(zip(g["stock_code"], g["target_weight"].astype(float)))
        if set(m) != {"226490", "229200"}:
            raise RuntimeError(f"Incomplete authoritative PQ signal {sd}")
        if abs(sum(m.values()) - 1.0) > 1e-9:
            raise RuntimeError(f"PQ equity-sleeve weights do not sum to 1 on {sd}")
        out[pd.Timestamp(ed)] = u.normalize({
            "KOSPI_ETF": 0.60 * m["226490"],
            "KOSDAQ150_ETF": 0.60 * m["229200"],
            "SHORT_PLUS": 0.40,
        })
    if not out:
        raise RuntimeError("No authoritative PQ targets formed")
    return out


u.download_prices = download_prices_capped
u.pq_targets = pq_targets_authoritative

if __name__ == "__main__":
    u.main()
