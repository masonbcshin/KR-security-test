# Exception — missing FRED US interbank April 2020, documented before any result

Run 40531405435 passed the pinned FRED source checks and then correctly FAILED CLOSED before any performance outputs because the original FRED US interbank series IR3TIB01USM156N has a single missing observation on 2020-04-01. The original source CSV is preserved **unaltered** as a blank.

Research amendment before observing any strategy result: use independent FRED TB3MS (3-month US Treasury Bill secondary market monthly rate) **0.14% for 2020-04 only** as a documented proxy for the missing US 3-month interbank quote. No other missing months may be imputed or substituted. TB3MS observations sourced directly from FRED historical provider for 2020-01 through 2020-07, value 2020-04 = 0.14%. This Treasury rate is not the same rate as interbank; basis risk remains; April 2020 will be sensitivity-tested +/- 2.00 percentage points annualized in final report, and the final result is research-only.

Core model / period / hedge policies / bootstrap gates unchanged. If any second missing month, fail closed.
