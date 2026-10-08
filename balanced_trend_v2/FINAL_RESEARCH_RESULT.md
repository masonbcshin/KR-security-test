# Balanced Trend Strategy Tournament — Final Research Result

기준일: 2026-08-26 KST  
검증 레포: `masonbcshin/KR-security-test`  
검증 PR: #26  
최종 Actions run: `32917196986`  
최종 artifact: `balanced-trend-v2-results` / id `9588599523`  
artifact digest: `sha256:b74d9fa136927199dfa60994d70d6cf83301c18c18cd8acd77c2b2162961c057`

## 공식 연구 판정

**NO_STATISTICALLY_VALIDATED_OPTIMUM**

사전등록된 종료 규칙에 따라 추가 SMA 기간, 가중치, threshold 탐색은 여기서 중단한다.

## 1. 구조 토너먼트 A~E

기존 `A_current_v1`이 B~E를 모두 이겼다. Primary OOS(next-open, 10bp) 기준:

| Candidate | CAGR | Sharpe | MDD | Calmar |
|---|---:|---:|---:|---:|
| A current v1 | 11.19% | 0.831 | -9.08% | 1.232 |
| C multi-horizon fixed | 10.71% | 0.801 | -8.43% | 1.271 |
| E robust risk managed | 5.36% | 0.669 | -4.46% | 1.203 |
| D multi-horizon inverse-vol | 5.12% | 0.645 | -4.55% | 1.125 |
| B SMA200 inverse-vol | 4.77% | 0.552 | -6.33% | 0.753 |

따라서 inverse-volatility와 volatility target을 추가한 복잡한 v2 구조는 승격하지 않는다.

## 2. v1 vs 정적 통제군

동일 30/30/15/15/10을 trend 없이 보유하는 `Z_static_fixed`와 비교했다.

| Candidate | CAGR | Sharpe | MDD | Calmar | Annual turnover |
|---|---:|---:|---:|---:|---:|
| A current v1 | 11.19% | 0.831 | -9.08% | 1.232 | 3.174x |
| Z static fixed | 13.17% | 0.818 | -17.76% | 0.741 | 0.352x |

v1은 MDD와 Calmar가 크게 우월하지만, 25bp next-open에서 Sharpe가 정적배분보다 낮았고 paired block bootstrap `P[Sharpe(A)>Sharpe(Z)] = 47.6%`로 70% gate에 실패했다.

따라서 **v1 trend filter의 alpha/risk-adjusted 우월성은 통계적으로 검증됐다고 선언하지 않는다.**

## 3. 최종 challenger F — SMA grid ensemble

사전 sensitivity grid였던 160/180/200/220/240을 결과를 보고 하나 고르지 않고 전부 동일가중했다. 각 자산 exposure는 5개 SMA signal 중 ON 비율(0/20/40/60/80/100%)이다.

Primary OOS(next-open, 10bp):

| Candidate | CAGR | Sharpe | MDD | Calmar | Annual turnover |
|---|---:|---:|---:|---:|---:|
| **F SMA-grid ensemble** | **11.58%** | **0.871** | **-8.40%** | **1.379** | 3.241x |
| A current v1 | 11.19% | 0.831 | -9.08% | 1.232 | 3.174x |
| Z static fixed | 13.17% | 0.818 | -17.76% | 0.741 | 0.352x |

Stress:

- 25bp next-open Sharpe: F **0.828** > Z 0.814 > A 0.789
- 10bp next-close Sharpe: F **0.877** > A 0.836 > Z 0.799
- paired block bootstrap `P[Sharpe(F)>Sharpe(A)] = 99.75%`
- paired block bootstrap `P[Sharpe(F)>Sharpe(Z)] = 58.45%`

Frozen promotion gates 7개 중 6개 PASS. 유일한 FAIL은 `bootstrap_F_gt_Z_ge_70pct`였다.

따라서 F를 **통계적으로 검증된 최적 전략**으로 승격하지 않는다.

## 4. 실전 해석

- 절대 CAGR만 우선하면 현재 표본에서는 Z static이 13.17%로 가장 높다. 대신 MDD가 -17.76%로 가장 크다.
- drawdown과 risk-adjusted 성과를 함께 보면 F가 관측 표본에서 가장 좋은 Pareto 위치다: A보다 CAGR/Sharpe/MDD/Calmar가 모두 개선됐고, 비용·체결 stress에서도 우위를 유지했다.
- 그러나 F는 기존 결과를 확인한 뒤 정의된 최종 challenger이며, 정적배분 대비 bootstrap gate도 실패했으므로 독립 OOS 증거로 과대해석하지 않는다.

## 5. 최종 실행 결정

1. **연구 결론:** 통계적으로 검증된 단 하나의 최적 전략은 아직 없다.
2. **기존 production 설계:** A(v1)를 즉시 160/180일 등으로 사후 변경하지 않는다.
3. **신규 production 후보:** F는 `v2-candidate`로만 보존한다. 실제 자금 전략으로 즉시 승격하지 않는다.
4. **현 시점 실전 기본값:** 이미 설계·운영 안전성이 확정된 A(v1)를 유지한다. 이 선택은 alpha 최적성 때문이 아니라 검증된 구조 중 단순성·낮은 MDD·운영 안정성 때문이라고 명시한다.
5. **F 승격에 필요한 다음 증거:** 이 연구에 사용되지 않은 미래 데이터의 전향적 SHADOW/PAPER 또는 명시적으로 고정된 독립 holdout에서 F와 A를 비교한다. 기존 2013~2026 데이터를 재최적화해 승격하지 않는다.

즉, 현재 production 판정은 **KEEP A(v1)**, research challenger는 **F**, 통계적 최적성 판정은 **NOT PROVEN**이다.
