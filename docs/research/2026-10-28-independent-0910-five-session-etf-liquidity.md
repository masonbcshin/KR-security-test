# KIS 비의존 09:10 국내상장 S&P500 ETF 독립 유동성 실증

- 수집/판정일: 2026-10-28 KST
- 현재 공개 연구 PR: https://github.com/masonbcshin/KR-security-test/pull/31
- 취득원: Yahoo Finance historical 5m data via catalogued `finance-yahoo-com/equities/history`; tickers `143850.KS`, `448290.KS`, `449180.KS`, `219480.KS`. **KIS 호출·계좌·주문 없음**.
- Unix UTC timestamp `00:10:00Z` = Asia/Seoul `09:10:00`; bar is **09:10~09:14:59의 체결가격 OHLCV**, not a bid/ask snapshot or fill. Trading volume is provider reported, can omit off-book/auction volumes and zero-volume bar stale price.
- Source catalogue documents up to 60d 5min history. Historical bar data can be revised and is licensed; report includes only limited observed samples, not feed repost.
- 2026-10-21/22/23/26/27 five actual regular KRX sessions, NOT actual first business days following month end; use only for **instrument selection research**, not monthly slippage gate certification.

## 09:10 5-minute traded volumes: direct independently fetched observations

| KST date | 143850 futures(H) shares | 448290 TIGER physical(H) shares | 449180 KODEX physical(H) shares |
|---|---:|---:|---:|
| 2026-10-21 | 70 | 1,621 | 5,796 |
| 2026-10-22 | 123 | 636 | 26,212 |
| 2026-10-23 | 48 | 358 | 16,167 |
| 2026-10-26 | 212 | 1,540 | 20,018 |
| 2026-10-27 | 102 | 195 | 16,015 |
| **Five-day median volume** | **102** | **636** | **16,167** |

Per-bar traded notional **estimated** = Yahoo 09:10-09:14 5min last price × provider 5min volume. Five-session median:
- 143850 ~ 786.7만원
- 448290 ~ 1,137.2만원
- **449180 ~ 2억 7,686만원**.

These values **do not reveal the executable bid/ask spread, the number of shares displayed at best offer, 09:10:00 available depth, price impact or potential queueing.** Large traded volume does not guarantee OUR order fill at the same price. Do not divide raw number of shares alone across ETFs with different per-unit prices; traded KRW value is the relevant comparative quantity.

Sources:
- https://finance.yahoo.com/quote/449180.KS/history/
- https://finance.yahoo.com/quote/448290.KS/history/
- https://finance.yahoo.com/quote/143850.KS/history/
- https://finance.yahoo.com/quote/219480.KS/history/

## 2026-10-27 public product/closing market checks

| attribute | 143850 futures(H) | 448290 TIGER spot(H) | 449180 KODEX spot(H) |
|---|---:|---:|---:|
| daily trade volume | 2,653 shares | 72,540 shares | 271,501 shares |
| daily traded value | 2.04억원 | approx 12.9억원 | 46.62억원 |
| AUM (approx) | 898억원 | 4,829억원 | 1.1조원 |
| advertised management total fee p.a. | 0.30% | 0.07% | 0.0099% |
| reported TER including other management expenses | not verified | about 0.24% | about 0.16% |

As-of dates vary by source for AUM and expense ratios. Figures come from live/dated KRX industry pages and public comparative services, require issuer PDS cross-verification before production. Expense ratio does **not** include unknown 09:10 spread or market impact; do not subtract current TER from historical NAV/AdjClose backtests a second time.

Sources:
- https://markets.hankyung.com/stock/143850
- https://markets.hankyung.com/stock/449180
- https://etfin.kr/etf/448290
- https://etfin.kr/etf/449180
- https://kind.krx.co.kr/disclosure/etfisudetail.do?method=searchEtfIsuSummary&strIsurCd=44918

## Official exchange liquidity-provider rule and 09:10 risk

KRX official LP rules: LP order obligations conditional on market spread threshold, may have up to 5 minutes after triggering situation; actual executable spread NOT guaranteed and some exemption applies. 09:10 exactly near spread submission deadline does not mean ETF quotes have already normalized; quote checks can require holding until 09:15 or 09:20, not blind orders. Official https://regulation.krx.co.kr/contents/RGL/03/03060103/RGL03060103.jsp.

## Final research decision (E2E instrument **selection**, not REAL permission)

- **Primary E2E candidate: 449180 KODEX 미국S&P500(H)** for spot hedged index replication, substantially stronger actual trade activity around 09:10, lower cited current TER and AUM advantage.
- Backup: 448290 TIGER 미국S&P500(H), slightly stronger 33-month v1.1 historical CAGR (+0.108%p overall) but significantly less 09:10 traded notional at observed sessions, reported higher TER.
- Baseline: 143850 futures(H) maintained unchanged for comparison until new version released.
- 2024-01..2026-09 v1.1 common portfolio study cannot establish winner with only 33 months; 449180 ex-dividend 2023-07 abnormal Yahoo difference 34.33 bp (before 2024 start), requiring official repair for longer backtests.
- **Full historic actual 09:10 bid/ask and our intended quantity fill: NOT OBSERVABLE from these public 5m trades.** Market order/Post is out of scope. REAL order validation requires timestamped authenticated top-of-book/iNAV and PAPER broker executions; independent feed can serve *external audit* only.
- Keep existing `v1.1` strategy_id/YAML untouched; **propose v1.2** with `143850 -> 449180` and the same other weights and 200SMA. Preserve read-only SHADOW validation and PAPER E2E broker reconciliation. Versioning is essential for DB target hash and accounting.

## Engineering execution controls (should be added in a separate production PR)

1. Use ETF price close RAW for SMA and dividend-adjusted total return solely for performance; map cash distribution to actual cash ledger only on provider settlement, verify taxes and ex-date holdings. No double counting.
2. Collect 09:10/09:15/09:20/09:30 authorized live GET **both best bid/ask and iNAV**; observe 5+ market days including **monthly rebalance session**, but thresholds need volatility/fee context, not arbitrary mandates.
3. Quote freshness and actual session day must be confirmed. Check ask/bid size >= intended quantity or split order, fair value and limit order bounded by maker price constraints; if no valid quote, skip/halt rather than force-fill.
4. Compare broker confirmed fill to independent 5-minute reference as **diagnostic only**; resampling/intraday liquidity not a guarantee.
5. Any switch of 09:10 to later time is an execution policy version, tested with replay and only promoted when measured price/deviation improves, not a modification to 200SMA.
