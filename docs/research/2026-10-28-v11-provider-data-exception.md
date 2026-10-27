# 2026-10-28 observed Yahoo data exception; still before any comparative returns were produced

Run 40600773448 confirmed 069500 had **one invalid bar on 2024-10-30**, a date *inside* the candidate common period; run failed closed before simulations or exposure decisions. This is a price-provider completeness issue, not a return result.

For research **only**:
1. Reject more than two invalid price rows per instrument inside the 2022-11..2026-09 comparison period; zero-fill, interpolation or future-reference fixes remain forbidden.
2. Exclude the exact missing dates through global INNER JOIN of all ETF trade dates, as prior KR-security-test instrument research does. Log excluded dates and affected symbols in manifest; do not misrepresent the resulting 200 observations as the same 200 true KRX trading sessions.
3. Flag **KIS exact SMA parity UNVERIFIED** irrespective of performance. Production/equity instruments must receive actual KIS bar repair or independent official market evidence and signal parity checks before any REAL promotion.
4. Keep locked SMA window of 200 usable rows after common-date alignment and 250 usable-row warmup; this amendment does NOT optimize the signal or ETF selection.

Original raw Yahoo records kept untouched at source and no KIS authenticated price proof is available for the missing row. More than two missing rows in the overlap triggers FAIL; a single missing KRX **month-end signal date** also FAILS, never permitted.
