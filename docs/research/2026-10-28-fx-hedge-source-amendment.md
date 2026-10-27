# 2026-10-28 Data-source Amendment (results blind)

Initial Actions run 40529471866 failed before producing metrics because the FRED public CSV endpoint timed out twice for DEXKOUS (50 seconds each). No strategy result was observed.

Change **transport only**: access the **same exact FRED IDs** DEXKOUS, IR3TIB01KRM156N and IR3TIB01USM156N via DBnomics mirror API (`api.db.nomics.world/v22/series/FRED/{ID}?observations=1`). Source provenance must explicitly list provider FRED and mirror DBnomics; no substitution of a different economic series without a further amendment. Official references remain https://fred.stlouisfed.org/.

Unchanged: SPY Yahoo adjusted data, 1998-2026 sample, 0/50/100 hedge, 200SMA calculations, forward formula, interest-rate lag, stress costs and basis, metrics, bootstrap, gates, seed. Fail closed if mirror has missing observations, malformed JSON, stale or insufficient history. Never fabricate observations.
