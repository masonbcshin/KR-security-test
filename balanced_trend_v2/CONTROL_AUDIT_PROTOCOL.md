# v1 static-control audit — preregistered after structural tournament

작성일: 2026-08-26 KST

## 목적

1차 A~E 구조 토너먼트에서 `A_current_v1`이 승리한 뒤, 그 결과와 별개로 v1의 핵심인 200SMA trend filter 자체가 동일 자산·동일 기본비중의 단순 정적 포트폴리오보다 가치가 있는지 검증한다.

이 감사는 **v1을 다른 파라미터로 최적화하지 않는다.** 통제군 하나만 추가한다.

## 통제군 Z — static_fixed

- 자산: A와 동일한 5 ETF
- 목표 비중: 30/30/15/15/10
- 추세 신호 없음
- 매월 동일 목표 비중으로 리밸런싱
- leverage/short 없음

## 공통 가정

- 데이터, 기간, adjusted-price 처리, next-open/next-close proxy는 `PROTOCOL.md`와 동일
- 비용 10/25/50bp per traded notional
- OOS-like: 2020-01-01 이후
- defensive ETF 월 수익률을 Sharpe의 cash proxy로 사용

## primary gate

A의 trend filter를 유효하다고 판정하려면 OOS-like에서 모두 만족해야 한다.

1. 10bp next-open Sharpe(A) > Sharpe(Z)
2. 10bp next-open Calmar(A) >= Calmar(Z)
3. 10bp next-open |MDD(A)| <= |MDD(Z)|
4. 25bp next-open Sharpe(A) > Sharpe(Z)
5. 10bp next-close Sharpe(A) > Sharpe(Z)
6. 동일 월을 묶은 12개월 circular block bootstrap 2,000회에서 P[Sharpe(A) > Sharpe(Z)] >= 70%

하나라도 실패하면 `V1_TREND_FILTER_NOT_VALIDATED`로 판정한다. 통과하면 `V1_TREND_FILTER_VALIDATED`다.

FULL/EARLY 결과는 진단용이며 primary gate를 바꾸지 않는다.
