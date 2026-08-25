#!/usr/bin/env python3
"""Authoritative entry point for corrected KR-CORE full runs.

`run_corrected_tournament.py` fixes the strategy specification.  This wrapper
also installs the same fractional-share `universe_cap` benchmark used by the
portable CI and preregistered long-reversal challenger, preventing a manual
corrected run from silently falling back to the integer-share simulator.
"""
from __future__ import annotations

import runpy
from pathlib import Path

import run_portable_tournament as rpt
from run_long_reversal_challenger import _save_fractional_benchmark


_ORIGINAL_SAVE = rpt.save_result


def _save_authoritative(root, name, sig, events, db, cfg):
    if name == "universe_cap":
        return _save_fractional_benchmark(root, sig, events, db, cfg)
    return _ORIGINAL_SAVE(root, name, sig, events, db, cfg)


rpt.save_result = _save_authoritative
runpy.run_path(
    str(Path(__file__).with_name("run_corrected_tournament.py")),
    run_name="__main__",
)
