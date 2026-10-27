# 사전등록 — USD/KRW FX Hedge Structural Study 1998–2026

2026-10-28 KST · Results-blind preregistration · 연구 브랜치: `research/fx-hedge-long-1998-2026`

## 목적
한국 원화 투자자의 미국 S&P500 30% 슬리브에 대해 **0%, 50%, 100% 환헤지** 중 어느 FX 정책이 장기 투자 및 월별 200거래일 SMA 추세추종에 적합했는지 역사적으로 비교. 단일 최고 ETF 종목 선정이나 즉시 REAL 교체의 근거로 사용하지 않는다.

## Data and observation timing
1. SPY Yahoo adjusted daily close (dividend/split-adjusted; investable US total-return proxy). 1998-01 ~ 2026-09 complete months, request through 2026-10-01 exclusive. Prices are adjusted and NOT the price-index `^GSPC`.
2. FRED `DEXKOUS` daily **KRW per 1 USD**; FRED OECD `IR3TIB01KRM156N` KRW 3-mo annualized interbank percent and `IR3TIB01USM156N` US 3-mo rates monthly.
3. Economic historical analysis, **not** KRX-executable exact fills. FX market day alignment uses latest date at or before US stock trade date (no future fill), max 4 calendar days stale; market close-time mismatch remains a limitation.
4. FRED monthly rate observation can be published/revised after its calendar period. Use **prior calendar month's** observed monthly rate for next month's forward-hedge carry, never same month's retrospective average. This is a conservative lagged historical approximation, **not point-in-time vintage**. Compare stress ±1%pa additional basis/spread drag.
5. No interpolating missing months, splicing future data or treating a single stale forex quote as valid. If coverage insufficient for 1998–2026, explicitly shorten and report; don't invent 28 years.

## Hedge math, monthly forward on starting NAV
For a monthly USD asset gross return `r`, FX ratio `x=S_end/S_start`, 1-month KRW USD forward `f = (1 + rKRW * d/365)/(1 + rUSD * d/365)` (covered interest parity approximation):
- unhedged KRW gross = `(1+r)*x`
- fully hedged KRW gross = `(1+r)*x + (f-x)`  [selling USD forward for period-start USD principal]
- 50% hedged = 50% each, linear monthly split
- transacting hedges: additional flat **25bp/year** of hedged fraction, secondary 0 / 100bp/year stress. Always report carry (+/-) separately from transaction spread.
- half-hedged is the constant 50% hedge **at each month start**, not optimized dynamically.
- no leverage and no net FX speculation. Zero U.S. equity exposure = KRW cash.

## Two distinct experiments
A. USD common-signal exposure — daily adjusted SPY closing price vs its rolling 200 US-stock-observation SMA, computed only through monthly signal date. Same US equity ON/OFF across all 3 hedging policies. No selection effect: isolates FX allocation. Risk OFF invests in KRW 3mo cash proxy.
B. Native-policy-signal exposure — unhedged daily KRW synthetic index = SPY_Adj_Close*USD/KRW; hedged daily synthetic return approximates rolling daily hedge with FX principal hedged and carry earned using lagged 3-month rates; 50% policy value series derived daily as 0.5 each with daily approximation. For each policy monthly SMA200 signal differs. Monthly return accounting still uses monthly forward math.
C. Buy-and-hold baseline (US sleeve only) all 3 FX policies.
- Monthly close-to-next-month close economic total returns; for strategy apply signal known at start month end to **subsequent month's monthly holding period**. 200 trading days warmup. 1998 onward stats after warmup, no same-month future signal.
- KRW cash monthly gross approximated `1 + rKRW_prior * elapsed_days / 365`.
- Portfolio-level **optional diagnostic** is deferred unless 4 other non-US asset histories/validated gold proxy are checked; do not make a fabricated 28-year v1.1 portfolio using missing gold history.

## Metrics and predeclared stress
- CAGR, annualized volatility, excess-return Sharpe (over KRW cash), Sortino, MDD, Calmar, turnover and U.S.-equity ON fraction, 5/10-year rolling subsamples.
- regime slices: 1998–2007, 2008–2017, 2018–2026; 2000–2002 dotcom, 2008–2009 GFC, 2020 Covid, 2022 US rate hiking. Report months in each.
- 12-month circular block paired bootstrap 4000, seed 20261028; `P[Sharpe(X)>Sharpe(Y)]` is fraction of resampled histories, NOT posterior probability or guaranteed alpha. No multiple-comparison correction => research evidence only.
- 0,25,100bp/year hedge transaction drag; interest-basis +/-100bp/year stress; transaction drag from portfolio holding cash? apply to hedged USD equity ON only.
- 2018–2026 forward-like holdout, earliest 1998–2017 characterization only; params **never optimized**.

## Research-only conclusion gate
Prefer unhedged/partial policy over 100% hedge ONLY if:
- lower/equal MDD (within +10% relative), higher Sharpe and higher Calmar versus hedge across both full sample and 2018–2026 holdout under B (native 200SMA);
- performance survives 100bp hedge-cost drag variation, basis stress, and observed stress regimes; reliable data quality.
Otherwise conclude `NO_ROBUST_HEDGE_POLICY_WINNER`; do not retrofit gates. An actual ETF hedge decision additionally requires overlapping ETF tracking parity and live KIS 09:10 spreads.
No modifications to private production repository or current strategy; all code/results in isolated research branch before user review.

## Footguns flagged in advance
- Interest-rate forward pricing formula assumes frictionless forward, counterparty access; broker ETF hedge execution is not exact. A future annualized hedging differential is carry, *not mechanically a fee*. Futures rolling cost is separate.
- Historical SPY adjusted price is a backward-adjusted proxy and may contain later adjustment revisions.
- 28-year U.S. economic proxy does not validate KRX order fill, tax, ETF tracking, distribution reinvestment, gold 411060 presence.
- End-month U.S. close only becomes available in Korea later; do not claim same-day 16:10 KST executable signal.
