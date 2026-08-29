# Gold instrument ablation — final result

기준일: 2026-08-29 KST

## 연구 질문

Balanced Trend v1의 금 15% sleeve를 `132030 KODEX 골드선물(H)`에서 `411060 ACE KRX금현물`로 교체할 근거가 있는가?

금 instrument 외의 자산, 비중, 200거래일 SMA, 월말 신호, 다음 거래일 execution proxy, 비용 stress는 고정했다.

## 검증 provenance

- Repository: `masonbcshin/KR-security-test`
- Branch: `research/gold-instrument-ablation-v1`
- Draft PR: `#27`
- Primary workflow run: `33241368436`
- Primary artifact: `gold-instrument-ablation-results`
- Artifact id: `9711453143`
- Artifact digest: `sha256:d1e2865098310353f5b5eef5d56364e8766b11c9ddbe7e4cc556e6d31a36423f`
- Data provider: Yahoo Finance via yfinance

## 1. 실제 ETF 공통구간 — Primary

공통 원시 데이터: 2021-12-15 ~ 2026-08-28  
200일 SMA history 확보 후 평가: 2022-11-01 ~ 2026-07-01, 45개월

10bp / next-open:

| Variant | CAGR | Sharpe | MDD | Calmar | Annual turnover |
|---|---:|---:|---:|---:|---:|
| 132030 골드선물(H) | 15.92% | 0.976 | -9.08% | 1.752 | 3.195x |
| **411060 KRX금현물** | **17.80%** | **1.113** | **-8.63%** | **2.063** | 3.305x |

실제 overlap의 사전등록 6개 gate는 모두 PASS했다.

- Sharpe: PASS
- Calmar: PASS
- MDD no more than 10% worse: PASS
- 25bp cost Sharpe: PASS
- next-close Sharpe: PASS
- paired 6-month circular block bootstrap 4,000회: `P[Sharpe(411060) > Sharpe(132030)] = 98.625%` — PASS

비용 stress에서도 411060 우위가 유지됐다.

25bp next-open Sharpe:
- 132030: 0.941
- 411060: **1.076**

50bp next-open Sharpe:
- 132030: 0.881
- 411060: **1.014**

10bp next-close Sharpe:
- 132030: 0.964
- 411060: **1.116**

## 2. 장기 synthetic physical-gold proxy — 사용 불가 판정

`GLD × USD/KRW`를 원화 비헤지 physical-gold proxy로 미리 정의해 2013~2026 장기 진단을 수행했다.

장기 지표 자체는 synthetic spot이 모두 우세했다.

| Variant | CAGR | Sharpe | MDD | Calmar |
|---|---:|---:|---:|---:|
| 132030 | 7.47% | 0.670 | -9.08% | 0.823 |
| Synthetic spot | **8.61%** | **0.811** | **-8.35%** | **1.031** |

그러나 이 proxy는 실제 411060과의 validation을 실패했다.

- 월간 수익률 correlation: 0.7987 (gate 0.95 미달)
- annualized tracking error: 13.11% (gate 6% 초과)

따라서 이 장기 결과는 **411060 교체의 근거로 사용하지 않는다.**

## 3. Frozen protocol verdict

기존 `PROTOCOL.md`의 엄격한 종료 규칙에 따른 자동 판정은:

**`KEEP_FUTURES_NO_REPLACEMENT_EVIDENCE`**

이다.

이 판정은 실제 overlap에서 411060이 졌기 때문이 아니라, 장기 synthetic proxy가 411060을 제대로 재현하지 못해 최종 strong-evidence gate를 완성할 수 없었기 때문이다.

## 4. 실무 해석

현재 증거는 두 층으로 나뉜다.

1. **실제 ETF 가격으로 확인 가능한 45개월에서는 411060이 132030을 명확히 이겼다.** CAGR, Sharpe, MDD, Calmar, 비용 stress, next-close, bootstrap이 모두 411060 쪽이다.
2. 그러나 411060 자체의 실제 history가 짧고, 장기 proxy가 validation에 실패했으므로 10년 이상 regime robustness를 확인했다고 볼 수 없다.

따라서 현 시점 product-level 판정은:

- Production v1의 132030을 즉시 교체하지 않는다.
- `411060 ACE KRX금현물`을 **최우선 gold challenger**로 승격한다.
- 동일 v1 200SMA 로직으로 132030과 411060을 SHADOW 병행 기록한다.
- 추가 과거 파라미터 튜닝은 하지 않는다.
- KRX 금현물지수의 공식 장기 history를 신뢰 가능한 방법으로 확보하면 별도 confirmatory test를 수행한다.

즉, **실제 관측 성과는 411060 우위지만, production 교체 판정은 아직 보류**다.
