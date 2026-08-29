from __future__ import annotations

import json
from pathlib import Path

import requests

URL = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Referer": "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd",
}
OUT = Path("gold_instrument_ablation/index_discovery.json")


def main():
    matches = []
    attempts = []
    for mktsel in ["ALL", "", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]:
        data = {
            "locale": "ko_KR",
            "mktsel": mktsel,
            "searchText": "금현물",
            "bld": "dbms/comm/finder/finder_equidx",
        }
        try:
            r = requests.post(URL, data=data, headers=HEADERS, timeout=20)
            item = {"mktsel": mktsel, "status": r.status_code}
            try:
                j = r.json()
                block = j.get("block1", [])
                item["rows"] = len(block)
                for row in block:
                    text = json.dumps(row, ensure_ascii=False)
                    if "금" in text or "Gold" in text or "GOLD" in text:
                        matches.append({"mktsel": mktsel, **row})
            except Exception:
                item["body"] = r.text[:300]
            attempts.append(item)
        except Exception as exc:
            attempts.append({"mktsel": mktsel, "error": repr(exc)})
    payload = {"matches": matches, "attempts": attempts}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
