# S&P500 hedged physical ETF vs futures — v1.1 portfolio confirmatory research

Registered before downloading/evaluating 2026-10-28 data. No private repo source file edit, no REAL/PAPER orders.

## Fixed production strategy
- baseline ETF asset weights: 069500 30%; 143850 30%; 148070 15%; **411060 gold spot 15%**; 153130 defensive cash proxy 10%.
- candidate replacement of S&P 30% only: 219480 futures hedged, 448290 TIGER physical hedged, 449180 KODEX physical hedged, 379800 KODEX physical unhedged, 360750 TIGER physical unhedged.
- optional 6-ETF 50/50 portfolio: 449180 physical hedged 15% + 379800 unhedged 15%, **single pooled US-sleeve signal** from 50/50 synthetic indicator; both OFF together; explicitly a proxy requiring implementation parity later.
- 200-trading-day SMA based on **raw closing prices** (not dividends-adjusted): if last close >= trailing 200 close mean then ON; if OFF the complete sleeve is transferred to 153130. Minimum raw 250 daily bars before the first signal.
- month-end KRX close signal -> next eligible session 09:10 EXECUTION (this study uses next adjusted OPEN only as proxy). 10,25,50 bp per traded notional costs and next adjusted CLOSE stress. All actual candidate comparisons against 143850 made on **the same matched execution dates**, not unequal histories.
- historical data Yahoo .KS: Open, Close, Adj Close, Dividends, Stock Splits where supported. Do not silently forward fill missing exchange trading dates/price. Truncate 2026-09 as last completed month, reserve 2026-10 for eventual forward study.
- use full-common actual ETF cohort of US candidates selected above; individual pairs may have longer histories but do not call unequal windows rankings. Last adjustment ratio: AdjOpen=Open*AdjClose/Close. This is **not actual 09:10 execution**.
- preserve historic monthly aggregate methodology from independent sp500_issuer_study; monthly-MDD **understates intramonth worst drawdown**. Include daily-close drawdown from real adjusted daily holding price with daily mark-to-market as separate metric if feasible.
- common fees 10,25,50bp vary jointly; incremental 09:10 execution slippage *differential* candidate vs baseline 0/10/25/50/100bp stress (baseline 10bp common) to see switching robustness. Reject "live 09:10 verified" without authenticated timestamped bid/ask, depth, print, and user-approved KIS read-only captures.

## Dividend controls
- distinguish KIS `FID_ORG_ADJ_PRC=0` split/corporate-action adjusted market price from Yahoo `Adj Close` total-return proxy. Production SMA runs on KIS close; label Yahoo raw-close signals as only provisional, subject to KIS parity.
- validate Yahoo historical `Dividends` against independently documented KRX/issuer distribution **ex/record dates and gross per-share amount**; document 449180 and 448290 pay in Jan/Apr/Jul/Oct. For 449180 independent observed records: 2026-07-31 40 KRW, 2026-04-30 42 KRW, 2026-01-30 40 KRW; 448290: 2026-07-31 42 KRW, 2026-04-30 40 KRW. Source https://etfro.com/etf/449180 and https://etfro.com/etf/448290, cross-validated official KODEX issuer distributions and KRX KIND profile.
- ex-date may differ from record date; allow max +/- 4 calendar days for the nearest matching Yahoo ex-event; flag mismatches; never silently double count dividends if adjusted OHLC already included them.
- if official cash distribution cannot reconcile to Yahoo events: `DIVIDEND_PARITY_UNVERIFIED`, block candidate REAL promotion; research-only adjusted-price performance can still be shown with prominent warning.
- corporate action splits also audited. Large abrupt adjusted/raw ratio changes without dividend/split evidence => invalid research result.
- 200SMA signal comparison with raw close vs Adj Close to quantify the effect of distribution adjustments; signal parity to KIS still requires true KIS candles.

## Gates and limits
- min 36 complete matched portfolio months for eligibility; Sharpe and Calmar improvement, abs(MDD) <= 1.1 baseline, 25bp/50bp and next-close Sharpe improvement. All must pass plus dividend parity AND quote parity for `REAL_REPLACEMENT_CANDIDATE`; other cases are `RESEARCH_ONLY`. A favorable 35-month backtest explicitly does not imply real price gate passed.
- Bootstrap 12mo circular block 3,000 seed 20261028 for matched monthly net returns, label as resampling frequency.
- report: candidate 143850,219480,449180,448290,360750,379800, 50% hedge combo; pairwise common dates, CAGR, Sharpe, MDD, Calmar, turnover, risk-OFF months, changed signals, end wealth, distribution audit, stress. Do not modify thresholds after results.
- No assumption that minute close, daily opening, and 09:10 executable bid/ask are the same. Real 09:10 requires separately captured orderbook snapshots and KIS GET evidence with confirmed observation timestamps and session date; market orders/executable prices cannot be deduced from public daily bars.
- No production config change; research PR draft; no merge without user approval.
