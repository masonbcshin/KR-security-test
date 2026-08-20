#!/usr/bin/env python3
"""CI wrapper for the portable tournament.

Only the portable_full_ml feature list is allowed to shrink to columns that are
actually produced by the pinned AlphaKRX commit. This prevents stale documented
feature names from being silently zero-filled or killing the whole comparison.
KR-CORE remains strict: if any core feature is missing, the run still fails.
"""
from __future__ import annotations

import json
from pathlib import Path

import run_portable_tournament as rpt

_ORIGINAL_TRAIN = rpt.train_ml_signals
_DROPPED: list[str] = []


def _train_ml_signals_portable(df, features, cfg, name, rebal_dates):
    global _DROPPED
    if name == "portable_full_ml":
        available = [c for c in features if c in df.columns]
        _DROPPED = [c for c in features if c not in df.columns]
        if _DROPPED:
            print(f"[portable_full_ml] unavailable pinned-engine features dropped: {_DROPPED}", flush=True)
        if len(available) < 10:
            raise RuntimeError(
                f"portable_full_ml has too few available features ({len(available)}): {available}"
            )
        return _ORIGINAL_TRAIN(df, available, cfg, name, rebal_dates)
    return _ORIGINAL_TRAIN(df, features, cfg, name, rebal_dates)


rpt.train_ml_signals = _train_ml_signals_portable
rpt.main()

# main() has completed successfully here. Add the portable-full compatibility
# audit next to the tournament results without modifying the research engine.
try:
    out = Path("outputs/tournament/portable_feature_compat.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "policy": "portable_full_ml may drop only features absent from the pinned engine output; KR-CORE is strict",
                "dropped_from_portable_full_ml": _DROPPED,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
except Exception as exc:
    print(f"[compat-audit] warning: {exc}", flush=True)
