# Gold instrument ablation — preregistered protocol

결과를 확인하기 전에 이 규칙을 고정한다.

## 질문

현재 balanced trend v1의 금 15% sleeve인 `132030 KODEX 골드선물(H)`를 `411060 ACE KRX금현물`로 바꾸는 것이 포트폴리오 수준에서 개선인가?

## Clean ablation

금 instrument 외에는 모두 고정한다.

- 069500 KODEX 200: 30%
- 143850 TIGER 미국S&P500선물(H): 30%
- 148070 KIWOOM 국고채10년: 15%
- Gold: 15%
- 153130 KODEX 단기채권: 10% + trend OFF sleeve
- 위험자산별 200 거래일 SMA binary filter
- `close >= SMA`: ON, `close < SMA`: OFF
- 월말 종가 signal, 다음 거래일 execution
- leverage/short 없음

후보:

- `G_FUTURES_H`: gold=`132030.KS`
- `G_SPOT_KRX`: gold=`411060.KS`

## Stage 1 — actual ETF overlap (primary)

Yahoo Finance 실제 ETF 일봉만 사용한다. 두 금 ETF와 나머지 ETF의 공통 거래일을 사용하고, 411060이 200일 SMA history를 확보한 뒤부터 동일 기간을 비교한다.

- signal: raw Close
- return price: total-return adjusted price
- primary execution proxy: next adjusted Open
- secondary: next adjusted Close
- traded-notional cost stress: 10 / 25 / 50 bp
- cash ETF return을 risk-free proxy로 사용한 excess-return Sharpe

Primary metrics: CAGR, excess Sharpe, MDD, Calmar, worst 12m, annual turnover.

Paired circular block bootstrap: 6-month blocks, 4,000 samples, seed `20260829`. 표본이 짧기 때문에 bootstrap은 보조 근거이며 결과를 보고 threshold를 낮추지 않는다.

### Actual-overlap gates

Spot가 futures보다 우월하다고 보려면 모두 만족해야 한다.

1. 10bp next-open Sharpe(SPOT) > Sharpe(FUTURES)
2. Calmar(SPOT) >= Calmar(FUTURES)
3. abs(MDD_SPOT) <= 1.10 * abs(MDD_FUTURES)
4. 25bp next-open Sharpe(SPOT) > Sharpe(FUTURES)
5. 10bp next-close Sharpe(SPOT) > Sharpe(FUTURES)
6. bootstrap P[Sharpe(SPOT) > Sharpe(FUTURES)] >= 70%

## Stage 2 — long-history synthetic physical-gold proxy (secondary)

짧은 411060 history를 보완하기 위해 `GLD * USDKRW`를 원화 비헤지 physical-gold proxy로 사용한다. 이는 411060 자체가 아니므로 반드시 proxy validation을 통과해야 한다.

- `GLD` adjusted prices × `KRW=X` adjusted prices
- benchmark는 실제 `132030.KS`
- 나머지 4개 ETF와 규칙은 동일
- 공통 구간은 데이터가 허용하는 최대 장기 구간

### Proxy validation

411060 실제 overlap에서 월간 수익률 기준:

- correlation(proxy, 411060) >= 0.95
- annualized monthly tracking error <= 6%

둘 중 하나라도 실패하면 Stage 2는 진단용일 뿐 승격 근거로 사용하지 않는다.

### Long-history gates

proxy가 유효할 때 다음을 모두 확인한다.

1. 10bp next-open Sharpe(proxy spot) > futures
2. Calmar(proxy spot) >= futures
3. abs(MDD_proxy_spot) <= 1.10 * abs(MDD_futures)
4. 25bp next-open Sharpe(proxy spot) > futures
5. 10bp next-close Sharpe(proxy spot) > futures

## Frozen decision

- Actual gates 전부 PASS + proxy validation PASS + long-history gates 전부 PASS: `SPOT_REPLACEMENT_EVIDENCE_STRONG`
- Actual gate 1~5 PASS지만 bootstrap만 FAIL: `SPOT_FORWARD_CANDIDATE_ONLY`
- 그 외: `KEEP_FUTURES_NO_REPLACEMENT_EVIDENCE`

어떤 결과가 나오더라도 금 비중, SMA 기간, 다른 ETF, threshold를 이 실험 결과에 맞춰 변경하지 않는다.

## Limitations

- Yahoo daily proxy는 실제 09:10 체결가가 아니다.
- 세금은 개인별로 달라 백테스트에 포함하지 않는다.
- synthetic proxy는 KRX 금시장 국내 basis/시차를 완전히 재현하지 못한다.
- 이 테스트는 금 instrument 교체만 판정하며 v1 전체 전략 최적성을 다시 주장하지 않는다.
