# Second transport amendment — frozen FRED observations (2026-10-28)

FRED graph CSV timed out in Action run 40529471866. DBnomics mirror URL returned 404 in run 40530197649. Neither run computed hedge returns.

The catalogued FRED series-observations provider successfully retrieved:
- FRED DEXKOUS (daily USD/KRW 1996-01-02 to 2026-09-30), pinned to fx_hedge_inputs/DEXKOUS.csv, 8022 dated observations.
- FRED IR3TIB01KRM156N (KRW 3-month interbank rates) and IR3TIB01USM156N (USD 3-month interbank rates), separately pinned to fx_hedge_inputs/ after complete retrieval.

This is only a transport/observation pin, **not a change to hedge formula, signals, evaluation sample, costs or parameter grid**. Future inputs loaded from repository files, no unreviewed internet substitution. Source data attributed to Federal Reserve Board and OECD via FRED; check public reproduction terms before merging the research branch. This PR is Draft; input cache is not production code.
