# 2026-10-28 data-quality amendment (prior to portfolio performance results)
The first v1.1 Action (40600608991) stopped while checking 069500 OHLC. The initial strict `any missing in 2010-2026` check failed before any portfolio metrics. Original instrument research silently `dropna`s; that is not satisfactory without an audit.
- Permit exclusion of explicitly counted Yahoo rows with missing, infinite or nonpositive OHLC **only prior to 2022-11-01**, the common candidate universe overlap. Never fill/interpolate returns.
- If any such row occurs on or after 2022-11-01, fail the study; no backtest built on incomplete live comparative window.
- Reject >1% invalid source rows per symbol.
- Store dropped row counts and dates to the output provenance.
- This is strictly an input validation amendment; SMA200, 250 minimum bars, weights, execution proxy and costs do NOT change.
