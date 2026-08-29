# ETN proxy data-source amendment

기준일: 2026-08-29 KST

`ETN_PROXY_PROTOCOL.md`의 전략·지표·gate·bootstrap·판정 규칙은 변경하지 않는다.

최초 실행에서 Yahoo Finance의 `530067.KS`가 과거 history를 제공하지 않고 1개 row만 반환해 ETN confirmatory test를 수행할 수 없었다. 이는 전략 결과가 아니라 데이터 공급 실패다.

따라서 `530067 삼성 KRX 금현물 ETN`에 한해 Naver 일봉(`fchart.stock.naver.com`)을 사용한다.

- signal Close: Naver Close
- execution Open proxy: Naver Open
- return Close proxy: Naver Close
- 530067은 이 연구에서 분배금 지급 내역이 없는 상품으로 확인되므로 raw price를 adjusted proxy로 사용한다.
- 나머지 ETF는 기존 Yahoo adjusted price를 계속 사용한다.
- proxy validation, 비용, SMA200, 비중, bootstrap, promotion gate는 그대로 유지한다.

이 amendment는 530067의 성과 결과를 확인하기 전에 커밋한다.
