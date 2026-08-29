# Official KRX Gold Spot Index confirmatory test

이 문서는 Stage 1 실제 ETF 결과와 GLD×KRW proxy 실패를 확인한 뒤, **공식 KRX 금현물지수**를 이용해 장기 노출을 독립적으로 확인하기 위해 새로 사전등록한다. 기존 `PROTOCOL.md`의 판정을 소급 변경하지 않는다.

## 목적

411060의 기초지수인 KRX 금현물지수의 2015년 이후 공식 history를 이용해, 현재 v1의 132030 골드선물(H) 15% sleeve보다 원화 금현물 노출이 장기적으로 더 나은 risk-adjusted 결과를 보이는지 확인한다.

## 고정 조건

- 나머지 ETF, 비중, 200거래일 SMA, 월말 signal은 기존 v1과 동일
- gold sleeve만 비교
  - benchmark: `132030.KS`
  - challenger: 공식 `KRX 금현물지수 (KRW)`
- 지수는 ETF가 아니므로 체결가를 모사하지 않는다. confirmatory test의 primary execution은 **다음 거래일 adjusted close**로 통일한다.
- 비용 stress: 10 / 25 / 50 bp
- signal은 각 gold series의 close와 200일 SMA
- cash ETF 153130 수익률을 excess-return Sharpe의 risk-free proxy로 사용
- 결과를 보고 SMA, 금 비중, 다른 ETF, threshold를 변경하지 않는다.

## Index validation gate

공식 KRX 금현물지수와 411060의 실제 overlap에서 월간 수익률을 비교한다.

- correlation >= 0.98
- annualized tracking error <= 4%

둘 다 통과해야 지수를 411060의 장기 proxy로 채택한다.

## Long-history gates

공통 장기구간에서 다음을 모두 통과해야 한다.

1. 10bp Sharpe(KRX spot index variant) > Sharpe(132030 variant)
2. Calmar(KRX spot index variant) >= Calmar(132030 variant)
3. abs(MDD spot) <= 1.10 * abs(MDD futures)
4. 25bp Sharpe(spot) > Sharpe(futures)
5. 50bp Sharpe(spot) > Sharpe(futures)
6. 12개월 circular block bootstrap 4,000회, seed `20260829`, P[Sharpe(spot)>Sharpe(futures)] >= 70%

## Decision

- index validation PASS + long-history gates ALL PASS: `SPOT_REPLACEMENT_RESEARCH_SUPPORTED`
- 그 외: `OFFICIAL_INDEX_CONFIRMATION_FAILED`

이 판정도 자동 production 교체를 의미하지 않는다. 실제 ETF overlap Stage 1 결과와 함께 product-level 의사결정 근거로 사용한다.
