#!/usr/bin/env python3
"""CI wrapper for build_marcap_db.py.

The pinned AlphaKRX financial ETL stores every DART line item, while the portable
research panel reads only six normalized accounting concepts. Filtering the raw
DART DataFrame before AlphaKRX's original parse/period/PIT logic keeps the same
availability-date and metadata semantics but avoids millions of irrelevant
row-wise SQLite inserts.
"""
from __future__ import annotations

import sys

import build_marcap_db as build

_ORIGINAL_LOAD_FINANCIALS = build.load_financials

# Include both legacy `ifrs_` spelling and normalized `ifrs-full_` spelling.
# AlphaKRX's own normalize_item_code() maps the former into the latter.
_REQUIRED_ITEM_CODES = {
    "ifrs_Assets", "ifrs-full_Assets",
    "ifrs_Equity", "ifrs-full_Equity",
    "ifrs_Liabilities", "ifrs-full_Liabilities",
    "ifrs_CashFlowsFromUsedInOperatingActivities",
    "ifrs-full_CashFlowsFromUsedInOperatingActivities",
    "ifrs_ProfitLoss", "ifrs-full_ProfitLoss",
    "ifrs_GrossProfit", "ifrs-full_GrossProfit",
}


def _lean_load_financials(alphakrx_root, db, start_year, end_year):
    sys.path.insert(0, str(alphakrx_root))
    from etl.financial_etl import FinancialDataLoader

    original_read = FinancialDataLoader.read_zip_file

    def read_relevant_only(self, zip_path):
        df = original_read(self, zip_path)
        if df.empty or df.shape[1] <= 10:
            return df
        code = df.iloc[:, 10].astype(str).str.strip()
        # Retain repeated header rows too; the original parser explicitly skips
        # them, which preserves its behavior while keeping index semantics.
        keep = code.isin(_REQUIRED_ITEM_CODES) | code.str.contains("항목코드", na=False)
        out = df.loc[keep].copy()
        print(
            f"[financial-lean] {zip_path.name}: {len(df):,} -> {len(out):,} rows",
            flush=True,
        )
        return out

    FinancialDataLoader.read_zip_file = read_relevant_only
    try:
        return _ORIGINAL_LOAD_FINANCIALS(alphakrx_root, db, start_year, end_year)
    finally:
        FinancialDataLoader.read_zip_file = original_read


build.load_financials = _lean_load_financials
build.main()
