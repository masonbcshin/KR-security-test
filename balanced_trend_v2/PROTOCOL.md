# Strategy Tournament v2 — preregistered protocol

작성일: 2026-08-26 KST  
상태: 결과 확인 전 사전등록  
원 사전등록: `masonbcshin/kis-balanced-trend-trader`의 `research/strategy-tournament-v2` 브랜치  
목적: `balanced_trend_krx_etf_v1`을 benchmark로 두고, 구조적으로 더 강건한 후보가 있는지 동일 데이터/비용/체결 가정으로 검증한다.

## 1. 검증 원칙

- 결과를 보기 전에 후보 규칙, 우선순위, 비용 스트레스, OOS 구간을 고정한다.
- CAGR 1위가 아니라 **after-cost OOS Sharpe → Calmar/MDD → CAGR → 안정성 → turnover** 순으로 판정한다.
- 후보가 benchmark를 이기지 못하면 v1을 유지한다.
- 파라미터 grid의 최고값을 새 전략으로 채택하지 않는다. sensitivity는 취약성 탐지용이다.
- 모든 후보는 long-only, no leverage, 월 1회 신호 생성이다.
- 데이터 오류/결측은 추정 보정하지 않고 실패시킨다.

## 2. 공통 유니버스

위험자산 4종 + 방어자산 1종:

| role | ticker | name | v1 base weight |
|---|---|---|---:|
| KR equity | 069500.KS | KODEX 200 | 30% |
| US equity | 143850.KS | TIGER 미국S&P500선물(H) | 30% |
| KR 10Y bond | 148070.KS | KIWOOM 국고채10년 | 15% |
| Gold | 132030.KS | KODEX 골드선물(H) | 15% |
| Defensive cash | 153130.KS | KODEX 단기채권 | 10% |

상품 교체(H/UH, 현물/선물)는 구조 토너먼트와 분리한다. 먼저 동일 유니버스로 신호/배분 구조를 비교하고, 승자 구조가 결정된 뒤 최근 공통기간에서 상품 구현을 비교한다.

## 3. 후보

### A — current_v1
- base weight: 30/30/15/15/10
- 위험자산별 raw close >= 200거래일 SMA이면 기본비중 유지
- 아니면 해당 비중 전부 defensive cash로 이동

### B — sma200_inverse_vol
- A와 동일한 200SMA binary trend
- 위험자산 예산 90%를 126거래일 realized volatility의 inverse-vol로 배분
- trend OFF 비중은 defensive cash로 이동
- leverage 없음

### C — multihorizon_fixed
- base weight는 A와 동일
- 각 위험자산의 raw price 63/126/252 거래일 수익률 부호를 사용
- 양(+)인 horizon 개수 / 3 을 exposure score (0, 1/3, 2/3, 1)로 사용
- 미사용 비중은 defensive cash로 이동

### D — multihorizon_inverse_vol
- B의 inverse-vol 예산 + C의 multi-horizon exposure
- 미사용 비중은 defensive cash로 이동

### E — robust_risk_managed
- D를 기본으로 함
- 63거래일 daily-return covariance로 목표 portfolio annualized volatility를 추정
- 목표 변동성 10%, `scale=min(1, 10%/estimated_vol)`로 위험자산만 축소
- leverage 금지, 축소분은 defensive cash
- 리밸런싱 시 각 위험자산 target-current 차이가 2.5%p 미만이면 거래하지 않고 defensive cash가 합계를 흡수

## 4. 데이터와 체결

- provider: Yahoo Finance via `yfinance`
- 시작 요청일: 2010-01-01
- 실제 검증 시작은 5종 모두 존재하고 252거래일 lookback이 확보된 첫 월말 이후
- signal: 각 월 마지막 공통 거래일 종가 이후 계산
- v1 contract를 맞추기 위해 signal의 가격은 raw close를 사용
- 성과 수익률은 분배금/분할을 반영한 adjusted price를 사용
- 기본 execution proxy: 다음 거래일 adjusted open
- 보조 execution proxy: 다음 거래일 adjusted close
- 09:10 실제 가격은 일봉으로 직접 재현할 수 없으므로 PAPER 단계에서 별도 검증한다.

## 5. 거래비용

ETF→ETF 교체의 양쪽 leg를 모두 비용으로 본다.

- base: 10bp / traded notional
- stress: 25bp
- severe stress: 50bp

세금은 계좌/상품/투자자별 과세가 달라 기계적 전략 순위에서 제외하고 별도 운영 검토 대상으로 둔다.

## 6. 평가 구간

- Full: 데이터 가용 전체
- OOS-like: 2020-01-01 이후
- Early: OOS 이전
- rolling 3Y
- crisis/regime label은 사후 임의 정의 대신 고정 구간으로만 보조 확인한다.

## 7. 핵심 지표

1. after-cost OOS Sharpe (defensive ETF return을 월별 risk-free proxy로 차감)
2. Calmar
3. MDD
4. CAGR
5. worst rolling 12M return
6. worst rolling 36M CAGR
7. rolling 36M positive ratio
8. annualized turnover
9. cost sensitivity
10. next-open vs next-close ranking stability

## 8. 강건성

- A SMA sensitivity: 160/180/200/220/240일. 최적값 선택에 사용하지 않는다.
- E multi-horizon sensitivity: (42,126,252), (63,126,252), (63,189,252). 최적 조합 선택에 사용하지 않으며 3개 중 최소 2개에서 A 대비 OOS Sharpe 우위를 요구한다.
- block bootstrap: 월 수익률을 12개월 원형 블록으로 2,000회 재표본하여 각 후보의 OOS Sharpe가 A보다 높은 비율을 계산한다.
- 후보 E가 기본 비용·OOS에서 우승하더라도 25/50bp 및 next-close에서 순위가 급락하면 채택하지 않는다.

## 9. 승자 규칙

새 전략으로 승격하려면 다음을 모두 만족해야 한다.

1. OOS-like after-cost Sharpe가 A보다 높다.
2. OOS-like Calmar가 A보다 낮지 않다.
3. MDD가 A보다 20% 이상 악화되지 않는다.
4. 25bp 비용에서도 A 대비 Sharpe 우위가 유지된다.
5. next-open/next-close 두 실행 proxy에서 방향이 일치한다.
6. bootstrap에서 후보 Sharpe > A 비율이 70% 이상이다.
7. E의 경우 사전등록한 horizon sensitivity 3개 중 최소 2개에서 A보다 OOS Sharpe가 높다.

아무 후보도 통과하지 못하면 `balanced_trend_krx_etf_v1`을 유지한다.

## 10. 범위 밖

- 머신러닝
- cross-sectional stock selection
- leverage/short
- 파라미터 최적화로 최고 Sharpe 찾기
- 09:10 intraday execution의 직접 검증
- 개인 세후수익률
