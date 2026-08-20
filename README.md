# KR Security Strategy Tournament

한국 주식 전략을 **동일한 공개 데이터·체결 규칙·거래비용으로 검증**하기 위한 연구 저장소입니다.

현재 결론과 수정 이력은 [`RESEARCH_VERDICT.md`](RESEARCH_VERDICT.md)에 기록합니다.

## Current verdict — 2026-08-20

**테스트한 active 전략 중 production 승격 후보는 없습니다.**

2018-01-01~2026-03-20 retrospective/pseudo-OOS 비교에서 비용 반영 `universe_cap` research benchmark가 risk-adjusted winner입니다.

| Strategy | Status | CAGR | Sharpe | MDD | Calmar |
|---|---|---:|---:|---:|---:|
| `universe_cap` | research winner | 10.70% | **0.599** | -40.97% | **0.261** |
| `lowvol_trend_long_reversal` | best active, rejected | 7.71% | 0.471 | -51.59% | 0.149 |
| corrected `lowvol_trend` | rejected | 7.31% | 0.449 | -52.53% | 0.139 |
| `q5_proxy` | rejected | 5.44% | 0.354 | -46.53% | 0.117 |
| corrected `kr_core_portable` | rejected | 2.99% | 0.249 | -47.88% | 0.062 |
| `portable_full_ml` | rejected | 0.24% | 0.127 | -58.89% | 0.004 |

Authoritative machine-readable table:

- `results/2026-08-20-authoritative-comparison.csv`

`universe_cap`은 연구용 fractional-share benchmark입니다. 따라서 이 결과를 그대로 실계좌 주문전략이라고 부르지 않습니다. 다음 production 단계에서는 별도의 사전등록된 integer-share / index-proxy baseline으로 번역해야 합니다.

## Candidates

1. `portable_full_ml` — AlphaKRX의 공개 feature 중 portable 경로에서 생성 가능한 feature를 사용하는 shallow LightGBM
2. `kr_core_portable` — corrected LowVol + Trend + Profitability + Earnings Growth + Liquidity LightGBM
3. `q5_proxy` — profitability + expected-growth proxy + conservative investment의 long-only q5-inspired proxy
4. `lowvol_trend` — corrected non-ML low-volatility + multi-horizon trend ensemble
5. `lowvol_trend_long_reversal` — 사전등록 challenger; corrected `lowvol_trend`에서 `mom36m` 부호만 +1→-1
6. `universe_cap` — 같은 eligible universe의 비용 반영 시가총액 가중 research benchmark

## Data

계정/비밀번호/API key 없이 public-data research DB를 재구성합니다.

- 가격·거래량·거래대금·시가총액: `FinanceData/marcap` 연도별 parquet
- 재무제표: 고정 AlphaKRX commit에 포함된 DART bulk ZIP
- 수정주가: AlphaKRX adjusted-price ETL
- 시장 수익률: 같은 large-cap investable universe의 전일 시총 가중 수익률

Full research DB:

- market data: **2011~2026**
- PIT financials: 2015~2025
- feature panel: 2015~2026-03-20
- evaluation: 2018~2026-03-20

2011년부터 가격을 적재하는 이유는 corrected `mom36m`의 장기 warm-up을 확보하기 위해서입니다.

## Important methodology labels

### KR-CORE

`KR-CORE`는 연구 과정에서 이미 2022~2026 정보를 참고해 설계되었습니다. 따라서 2018~2026 결과는 **retrospective/pseudo-OOS**이며 genuine untouched forward OOS가 아닙니다.

초기 portable 구현에는 두 오류가 있었습니다.

1. `mom36m`을 최근 756거래일 수익률로 잘못 구현
2. `conditional_momentum` 누락으로 11개가 아닌 10개 feature 사용

수정본은:

- `mom36m` = 월별 `t-36`~`t-13` 누적수익률
- 11개 KR-CORE feature 복원

으로 재실행했습니다. 두 독립 GitHub Actions corrected run의 `comparison.csv`와 KR-CORE `summary.json`은 byte-identical했습니다.

### VKOSPI caveat

정확한 frozen KR-CORE는:

`conditional_momentum = mom_21d * (1 - vkospi_level_pct)`

을 사용합니다.

현재 public portable DB에는 역사적 `deriv_index_daily`/VKOSPI가 없으므로 pinned AlphaKRX의 neutral fallback `vkospi_level_pct=0.5`가 적용됩니다. 따라서 현재 결과는 **`kr_core_portable`**이고 exact frozen VKOSPI-conditioned v1의 완전 복제는 아닙니다.

### q5 / Full ML labels

- `q5_proxy`는 학술 q5/HMXZ의 정확한 복제가 아닙니다.
- `portable_full_ml`은 공개 AlphaKRX Full ML과 동일하지 않습니다. unavailable macro/VKOSPI 입력을 그대로 귀속시키지 않습니다.

## Common rules

- KOSPI + KOSDAQ
- 시가총액 2,000억원 이상
- 종가 2,000원 이상
- 20일 평균 거래대금 하위 20% 제외
- 금융업 제외
- 양(+)의 자기자본 필요
- DART sector 없는 종목 제외
- accrual hard gate 없음
- 42거래일 리밸런싱
- ML: 3년 rolling train, 43거래일 embargo
- T+1 수정종가 체결
- target 50종목, equal target weight
- 기존보유 rank <= 90 우선 유지
- 신규 rank <= 28 우선 채택
- 50종목 미달이면 미보유 rank <= 90에서 잔여 슬롯 fill
- 매수비용 0.35%, 매도비용 0.55%
- stop-loss / market-timing 없음

`buy_rank=28`은 strict entry ceiling이 아니라 priority threshold입니다.

## Benchmark rule

`universe_cap`은 수백 종목의 시총비중을 정확히 표현하기 위해 **fractional shares**를 사용합니다.

1억원 가상계좌에 whole-share 제약을 적용하면 수백 종목의 작은 목표금액이 1주 가격보다 작아져 artificial cash drag가 발생하므로 benchmark를 왜곡합니다.

- T+1 execution
- 같은 side-specific costs
- 같은 eligible universe
- fractional-share weights

을 authoritative benchmark rule로 사용합니다.

초기 corrected workflow 한 번이 base integer simulator를 직접 호출하는 문제가 있었지만, benchmark signals가 기존 full run과 byte-identical임을 확인했고 authoritative comparison은 fractional benchmark를 사용해 교정했습니다. 자세한 내용은 `RESEARCH_VERDICT.md`를 참조합니다.

## Long-reversal challenger

PR #1에 결과 확인 전에 다음을 사전등록했습니다.

- corrected LowVol+Trend의 모든 규칙 유지
- **단 하나:** `mom36m` sign `+1 -> -1`

결과:

- corrected LowVol+Trend Sharpe `0.449`
- Long-Reversal Sharpe `0.471`
- cap benchmark Sharpe `0.599`

Long-Reversal은 active 후보를 개선했지만 production 승격 기준을 넘지 못했습니다.

## GitHub Actions

### Default PR smoke

통합 오류 탐지용이며 승자 판정용이 아닙니다.

- market data: 2018~2024
- PIT financials: 2019~2024
- feature panel: 2021~2024
- evaluation: 2024

검증 범위:

`public data -> PIT financials -> adjusted prices -> features -> model/static score -> T+1 transaction ledger`

### Manual research workflows

비용이 큰 full research / anomaly audit / long-reversal run은 완료 후 `workflow_dispatch` 전용으로 전환했습니다.

## Outputs

전략별 Actions artifact:

- `signals.csv`
- `transactions.csv`
- `position_ledger.csv`
- `equity_curve.csv`
- `summary.json`

연구 비교/감사:

- `comparison.csv`
- `run_manifest.json`
- `winner_report.md`
- `data_audit.json`
- `kr_core_spec_audit.json`
- `portable_feature_compat.json`
- `RESEARCH_VERDICT.md`
- `results/2026-08-20-authoritative-comparison.csv`

## Winner rule

CAGR만 최대화하지 않습니다.

1. after-cost Sharpe
2. Calmar / MDD
3. CAGR 및 `universe_cap` 대비 alpha
4. subperiod 안정성
5. turnover / cost burden

한 특정 장세만 보고 기존 전략을 소급 재튜닝하지 않습니다. 새로운 target, feature, concentration rule, regime rule은 **별도 challenger로 사전등록한 뒤** 테스트합니다.
