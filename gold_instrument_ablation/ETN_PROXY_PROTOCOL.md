# KRX Gold Spot ETN proxy confirmatory test

이 문서는 411060 실제 overlap 결과를 확인한 뒤, 공식 KRX 금현물지수 원천 history를 익명 runner에서 안정적으로 확보하지 못한 상황에서 **결과를 보기 전에** 별도 확인실험을 사전등록한다.

## Proxy

`530067 삼성 KRX 금현물 ETN`은 2019-11-05 상장되어 411060과 동일한 `KRX 금현물지수`를 기초지수로 한다. 실제 상장 가격을 사용한다.

## Validation

530067을 411060의 장기 proxy로 사용하기 전에 두 상품의 공통구간 월간 adjusted-return을 비교한다.

- correlation >= 0.98
- annualized tracking error <= 4%

둘 다 통과해야 long proxy로 인정한다.

## Clean ablation

나머지는 balanced trend v1과 동일하다.

- 069500 30%
- 143850 30%
- 148070 15%
- gold 15%
- 153130 10% + OFF sleeve
- 위험자산별 200거래일 SMA binary filter
- 월말 signal
- primary: next adjusted open
- secondary: next adjusted close
- traded-notional costs: 10/25/50bp

비교:
- benchmark gold = `132030.KS`
- spot proxy gold = `530067.KS`

## Gates

proxy validation이 PASS한 상태에서 모두 만족해야 한다.

1. 10bp next-open Sharpe(spot proxy) > futures
2. Calmar(spot proxy) >= futures
3. abs(MDD spot proxy) <= 1.10 * abs(MDD futures)
4. 25bp next-open Sharpe(spot proxy) > futures
5. 50bp next-open Sharpe(spot proxy) > futures
6. 10bp next-close Sharpe(spot proxy) > futures
7. 12개월 circular block bootstrap 4,000회, seed `20260829`, P[Sharpe(spot proxy)>Sharpe(futures)] >= 70%

## Decision

- validation PASS + all gates PASS: `KRX_SPOT_LONG_PROXY_SUPPORTS_REPLACEMENT`
- otherwise: `KRX_SPOT_LONG_PROXY_NOT_CONFIRMED`

이 결과는 411060 자체의 수익률을 소급 생성하지 않는다. 동일 기초지수의 실제 장기 상장상품을 이용해 KRX spot exposure의 regime robustness를 보조 검증하는 목적이다.
