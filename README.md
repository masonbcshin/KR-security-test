# KR Security Strategy Tournament

한국 주식 전략을 **공개 데이터만으로 재현**하기 위한 연구 저장소입니다.

## 목적

동일한 유니버스·체결 규칙·거래비용으로 다음 후보를 정면 비교합니다.

1. `portable_full_ml` — AlphaKRX의 공개 feature 중 marcap + DART만으로 재현 가능한 feature를 사용하는 shallow LightGBM
2. `kr_core_portable` — LowVol + Trend + Profitability + Earnings Growth + Liquidity의 축소 LightGBM
3. `q5_proxy` — profitability + expected-growth proxy + conservative investment의 long-only q5-inspired proxy
4. `lowvol_trend` — 비ML low-volatility + multi-horizon trend ensemble
5. `universe_cap` — 같은 eligible universe의 비용 반영 시가총액 가중 benchmark

## 데이터

계정/비밀번호/API key가 필요하지 않습니다.

- 가격·거래량·거래대금·시가총액: `FinanceData/marcap` 연도별 parquet
- 재무제표: 고정된 AlphaKRX commit에 포함된 DART bulk ZIP
- 수정주가: AlphaKRX adjusted-price ETL로 재구성
- 시장 수익률: 같은 large-cap investable universe의 전일 시총 가중 수익률로 구성

marcap은 역사적 시점의 전종목 행을 포함하므로 현재 상장종목 목록을 과거에 소급하는 방식보다 survivorship bias 위험이 낮습니다. 종목명은 표시용이고 매매 가능 여부/시장구분은 일별 marcap row를 사용합니다.

## 중요한 라벨

`portable_full_ml`은 **AlphaKRX가 공개한 Full ML과 동일한 전략이 아닙니다.** 원본에는 VKOSPI/파생지수 macro interaction이 있으나 공개 portable run에서는 이를 제거합니다. 따라서 원본 AlphaKRX의 과거 수익률을 이 모델에 귀속시키지 않습니다.

`q5_proxy` 역시 학술 q5/HMXZ의 정확한 복제본이 아니라 long-only 비교용 proxy입니다.

`KR-CORE`는 이미 연구 과정에서 2022~2026 자료를 참고해 설계됐으므로 2018~2026 결과는 **retrospective/pseudo-OOS**입니다. 진짜 forward OOS로 부르지 않습니다.

## 공통 규칙

- KOSPI + KOSDAQ
- 시가총액 2,000억원 이상
- 종가 2,000원 이상
- 20일 평균 거래대금 하위 20% 제외
- 금융업 제외
- 양(+)의 자기자본 필요
- DART sector가 없는 종목 제외 — ETF/ETN/우선주 등 비기업 증권의 혼입을 줄이는 공통 eligibility gate
- accrual hard gate 없음
- 42거래일 리밸런싱
- ML: 3년 rolling train, 43거래일 embargo
- T+1 수정종가 체결
- 신규 rank <= 28, 기존보유 rank <= 90 유지
- 최대 50종목, equal target weight
- 매수비용 0.35%, 매도비용 0.55%
- stop-loss / market-timing 없음

## 결과물

각 전략별로 Actions artifact에 다음 파일을 남깁니다.

- `signals.csv`
- `transactions.csv`
- `position_ledger.csv`
- `equity_curve.csv`
- `summary.json`

전체 비교:

- `comparison.csv`
- `winner_report.md`
- `run_manifest.json`
- `data_audit.json`

`position_ledger.csv`는 실제 T+1 진입/청산, 추가매수/부분매도까지 반영한 round-trip ledger입니다. T+1에 종목이 거래불가이면 가상 체결을 만들지 않습니다.

## GitHub Actions

PR에서는 비용과 오류 탐지를 위해 기본적으로 smoke 구간을 실행합니다.

- market data: 2018~2024
- feature panel: 2019~2024
- evaluation: 2022~2024

워크플로의 `Run workflow`에서 `tier=full`을 선택하면:

- market data: 2014~2026-03-20
- feature panel: 2015~2026-03-20
- evaluation: 2018~2026-03-20

전체 토너먼트를 실행합니다.

## 승자 판정

CAGR만 최대화하지 않습니다.

1. after-cost Sharpe
2. Calmar / MDD
3. CAGR 및 `universe_cap` 대비 alpha
4. 2018~2021 / 2022~2026 subperiod 안정성
5. turnover / cost burden

한 특정 장세에만 의존한 결과는 자동 승격하지 않습니다.
