# S&P500 ETF 전 운용사 상품 교체 연구 — 사전등록 2026-10-27

## 전제와 연구 의사결정
- benchmark v1.1: 069500 30%, 미국 143850 30%, 148070 15%, 금 411060 15%, 단기채 153130 10%.
- 유일한 실험 변수는 미국주식 30% ETF. 나머지 비중, 금 현물, 200거래일 SMA, 월말 종가 신호, 다음 거래일 adjusted open/close proxy, 10/25/50bp 거래비용 고정.
- 상품 단독 성과가 아니라 위 포트폴리오 전체의 Sharpe/CAGR/MDD/Calmar/turnover로 비교한다.
- 모든 국내 상장 일반 S&P500 시가총액가중 1배 패시브 상품을 포함한다. 운용사별 일반/환헤지형, 선물형 포함. 커버드콜·레버리지·인버스·동일가중·ESG·액티브·섹터·혼합자산은 다른 전략이므로 제외.
- 상품 종류별 주식현물형/선물형과 환헤지/환노출은 별도 축이다. 공식 상품 기본구조 자료로 검증한다.

## 고정 universe (17개)
- futures_hedged: 143850 TIGER 미국S&P500선물(H) 미래에셋, 219480 KODEX 미국S&P500선물(H) 삼성.
- physical_hedged: 448290 TIGER 미국S&P500(H) 미래에셋, 449180 KODEX 미국S&P500(H) 삼성, 453330 RISE 미국S&P500(H) KB, 449780 KIWOOM 미국S&P500(H) 키움, 269540 PLUS 미국S&P500(H) 한화.
- physical_unhedged: 360750 TIGER 미국S&P500 미래에셋, 379800 KODEX 미국S&P500 삼성, 360200 ACE 미국S&P500 한투, 379780 RISE 미국S&P500 KB, 433330 SOL 미국S&P500 신한, 444490 WON 미국S&P500 우리, 449770 KIWOOM 미국S&P500 키움, 429760 PLUS 미국S&P500 한화, 432840 HANARO 미국S&P500 NH아문디, 0026S0 1Q 미국S&P500 하나.
- 세그먼트 구간: 전 17종 공통구간(자료충족한 종목만; 최단 상품의 SMA warmup 후), >=2023년 이후 24개월 이상 가능한 선별군, 2020 이후 36개월 이상 가능한 긴 상품. 모든 구간 표본수 명시. 경쟁자가 동일 기간을 공유하지 않으면 직접 순위 매기지 않는다.
- 단일 원본은 Yahoo yfinance OHLC + Adj Close. Yahoo 결측 시 원칙적으로 NO_DATA, 다른 데이터 소스는 사전 명시 후 독립 재실행한다. Naver 종가를 adjusted total-return으로 가장하지 않는다.
- 비용 10,25,50bp (buy/sell traded notional). adjusted open = open*(adj close/close) proxy. 09:10 실제 체결/호가, 세금, 개별 상품 실부담보수·증권사 spread는 검증 불가. 100% 체결가능한 값으로 주장 금지.
- 실제 분배금이 adjusted-close 데이터에서 올바르게 반영되었는지 재점검 필요. Yahoo 결측/원화환산/분배금 정책 변경 시 각 후보를 UNVERIFIED로 표시.
- 월간 전략 주기상 2026년 10월 월말이 끝나기 전 데이터는 10월 부분 월을 완전 월말 신호로 취급하지 않는다.

## 평가와 Gate (결과 보기 전 고정)
- primary: 모든 유효 후보의 공통 평가기간, 10bp next adjusted open; 비용25,50bp, next adjusted close stress.
- pairwise: 143850과 각 후보의 동일 신호일·동일 체결일의 월간 수익률/위험을 pair alignment 후 비교한다; 아래 기준은 탐색적이며 진정한 OOS 우월성은 전향 SHADOW에서 판단.
- paired circular 12개월 bootstrap 3000회 seed 20261027: P[Sharpe(candidate)>Sharpe(143850)] bootstrap resampling win fraction (posterior true probability가 아님).
- 승격 검토 기준 (같은 비교기간): 10bp Sharpe 증가, Calmar 증가, abs(MDD)<=1.10*143850, 25bp Sharpe 증가, 50bp Sharpe 증가, next-close Sharpe 증가, bootstrap win fraction>=0.70; sample>=36 monthly returns. 모두 통과하더라도 **RESEARCH_CANDIDATE_ONLY**, REAL 자동 승격은 금지.
- FX 노출 변경 효과와 상품별 비용 우위를 분리하고, observed historical winner를 새로운 미래 OOS로 오인하지 않는다. 17개 다중비교로 인한 data-snooping 경고; 최고의 종목 1개 임의 선택 금지.
- 가격 이상치/2026 부분월/결측시 no verdict rather than fabricated ranking; 공통구간 비교 불가능하면 이유 공개.
- 최종 ETF 선정은 상품군 (H/unhedged) 우선 판단 후 동급에서는 실비용(TER+거래비용), AUM, 거래대금, iNAV 괴리, 실제 09:10 spread 자료 별도 운영 관측으로 결정.

## 독립성
본 문서는 최초 실행 결과를 보기 전에 작성. 파라미터/ETF 유니버스를 결과 이후 변경 시 amendment 분리. 기준 전략 원본 소스는 private repo에서 복사하지 않음. private repo 기존 문서 불변.
