# Final challenger protocol — SMA-grid ensemble

작성일: 2026-08-26 KST  
상태: **F 결과 확인 전 동결**

## 목적

기존 A~E 토너먼트에서는 `A_current_v1`이 승리했지만, 정적 30/30/15/15/10 통제군과 비교했을 때 25bp Sharpe 및 paired bootstrap 70% gate를 통과하지 못했다. 동시에 사전등록된 SMA sensitivity에서 단일 200일 선택의 parameter risk가 확인됐다.

이제 결과를 본 뒤 160일/180일 중 하나를 고르는 것을 금지하고, 기존에 사전등록되어 있던 SMA grid **160/180/200/220/240 전체를 동일가중**으로 사용하는 단 하나의 최종 challenger만 허용한다.

## F — `F_sma_grid_ensemble`

- 자산 및 기본비중은 v1과 동일: 위험자산 30/30/15/15, defensive 10.
- 각 위험자산에서 160/180/200/220/240일 SMA binary signal 5개를 계산한다.
- exposure = 양(ON) signal 수 / 5, 즉 0/20/40/60/80/100%만 허용한다.
- 각 위험자산의 미사용 비중은 defensive ETF로 이동한다.
- 월말 신호, 다음 거래일 체결, long-only, no leverage는 기존과 동일하다.
- 특정 SMA를 제거·가중하지 않는다.
- 결과 확인 후 grid를 변경하지 않는다.

## 비교군

- A: 현재 `A_current_v1` (200SMA binary)
- Z: `Z_static_fixed` (동일 30/30/15/15/10, trend 없음)
- F: `F_sma_grid_ensemble`

세 전략은 동일 시작일과 동일 리밸런싱 날짜를 사용한다.

## 실행 스트레스

- execution: next-open / next-close
- cost: 10bp / 25bp / 50bp per traded notional
- primary window: 2020-01-01 이후 OOS-like
- paired circular block bootstrap: 12개월 block, 2,000회, seed 20260826

## F 승격 gate

F를 최종 전략으로 승격하려면 **모두** 만족해야 한다.

1. next-open 10bp OOS Sharpe > A와 Z 모두
2. next-open 10bp OOS Calmar >= A
3. next-open 10bp OOS MDD가 A보다 20% 넘게 악화되지 않음
4. next-open 25bp OOS Sharpe > A와 Z 모두
5. next-close 10bp OOS Sharpe > A와 Z 모두
6. bootstrap P[Sharpe(F)>Sharpe(A)] >= 70%
7. bootstrap P[Sharpe(F)>Sharpe(Z)] >= 70%

## 종료 규칙

- F가 모든 gate를 통과하면 `PROMOTE_F_SMA_GRID_ENSEMBLE`.
- 하나라도 실패하면 추가 SMA/기간/가중치 탐색을 중단한다.
- 실패 시 최종 연구 판정은 `NO_STATISTICALLY_VALIDATED_OPTIMUM`으로 고정한다.
- 이 경우 실전 후보는 v1을 유지하되, 이유는 **alpha 우월성**이 아니라 현재 시험된 구조 중 가장 강한 drawdown/Calmar 방어와 운영 단순성이다.
- 160/180 등 사후 최적 파라미터로 변경하는 것은 금지한다.
