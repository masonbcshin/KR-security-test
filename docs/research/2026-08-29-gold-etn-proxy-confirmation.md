# KRX Gold Spot ETN proxy confirmation

기준일: 2026-08-29 KST

이 문서는 기존 gold ablation 결과를 수정하지 않고, 동일 KRX 금현물지수를 추종하는 장기 상장상품을 이용한 별도 confirmatory result를 기록한다.

## 결론

**`KRX_SPOT_LONG_PROXY_SUPPORTS_REPLACEMENT`**

Balanced Trend v1의 금 15% sleeve는 연구 관점에서 `132030 KODEX 골드선물(H)`보다 `411060 ACE KRX금현물`로 교체하는 쪽이 더 강하게 지지된다.

## Proxy 선택과 검증

`530067 삼성 KRX 금현물 ETN`은 2019-11-05부터 거래되며 411060과 동일한 `KRX 금현물지수`를 추종한다. Yahoo가 530067 history를 제공하지 않아, 결과 확인 전에 별도 amendment를 기록하고 530067만 Naver 일봉 OHLC를 사용했다. 전략 규칙과 gate는 변경하지 않았다.

411060과 530067의 실제 overlap 월간 수익률 검증:

- overlap months: 56
- 2022-01 ~ 2026-08
- monthly return correlation: **0.99755**
- annualized tracking error: **1.524%**
- preregistered gates: correlation >= 0.98, tracking error <= 4%
- **Proxy validation: PASS**

따라서 530067은 이 confirmatory test에서 KRX 금현물 exposure의 장기 상장 proxy로 사용 가능하다고 판정했다.

## Portfolio-level result

나머지 자산, 비중, 200일 SMA, 월말 signal, next-open/next-close, 거래비용은 기존 v1과 동일하다.

Primary 10bp / next-open, 71개월 (2020-09-01 ~ 2026-07-01):

| Gold sleeve | CAGR | Sharpe | MDD | Calmar | Annual turnover |
|---|---:|---:|---:|---:|---:|
| 132030 골드선물(H) | 11.64% | 0.842 | -9.08% | 1.281 | 3.265x |
| **530067 KRX 금현물 ETN proxy** | **13.47%** | **1.008** | **-8.12%** | **1.659** | **3.159x** |

모든 사전등록 gate PASS:

- 10bp next-open Sharpe: PASS
- Calmar: PASS
- MDD no more than 10% worse: PASS (실제로 더 낮음)
- 25bp Sharpe: PASS
- 50bp Sharpe: PASS
- next-close Sharpe: PASS
- 12개월 circular block bootstrap 4,000회: `P[Sharpe(KRX spot proxy) > Sharpe(132030)] = 100%` — PASS

Cost stress next-open Sharpe:

| Cost | 132030 | KRX spot proxy |
|---|---:|---:|
| 10bp | 0.842 | **1.008** |
| 25bp | 0.800 | **0.966** |
| 50bp | 0.728 | **0.895** |

10bp next-close Sharpe:

- 132030: 0.826
- KRX spot proxy: **0.986**

## Combined evidence

### 411060 actual ETF overlap

2022-11 ~ 2026-07, 45개월:

- 132030: CAGR 15.92%, Sharpe 0.976, MDD -9.08%, Calmar 1.752
- 411060: CAGR **17.80%**, Sharpe **1.113**, MDD **-8.63%**, Calmar **2.063**
- `P[Sharpe(411060)>Sharpe(132030)] = 98.625%`
- actual-overlap gates 6/6 PASS

### Same-index longer proxy

2020-09 ~ 2026-07, 71개월:

- 132030: CAGR 11.64%, Sharpe 0.842, MDD -9.08%, Calmar 1.281
- KRX spot proxy: CAGR **13.47%**, Sharpe **1.008**, MDD **-8.12%**, Calmar **1.659**
- bootstrap probability = **100%**
- confirmatory gates 7/7 PASS

두 독립적인 실제 상장상품 기반 비교가 같은 방향을 보였다.

## Research decision

금 instrument 수준에서 다음을 권고한다.

- 기존 v1의 132030을 연구 benchmark로 보존한다.
- 새 구현 후보는 **v1.1**로 분리한다.
- v1.1은 다른 규칙을 바꾸지 않고 gold sleeve만 `411060 ACE KRX금현물`로 교체한다.
- 금 비중 15%, SMA200, 월말 리밸런싱, 나머지 ETF는 변경하지 않는다.
- 실제 REAL 전에는 KIS SHADOW/PAPER에서 주문 가능 여부, 호가/spread, 09:10 execution tracking을 확인한다.

이 결과는 v1 전체의 글로벌 최적성을 의미하지 않으며, **gold instrument 교체에 대한 clean ablation 판정**이다.

## Final artifact provenance

- public repo: `masonbcshin/KR-security-test`
- branch: `research/gold-instrument-ablation-v1`
- draft PR: #27
- final confirmatory run: `33241688057`
- artifact: `gold-instrument-ablation-results`
- artifact id: `9711543993`
- digest: `sha256:7b488a756908c46f9f5445dba0a5f61fa85b2b03dccb84efaa3d770cde43b8f4`
