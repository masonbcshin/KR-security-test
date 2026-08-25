#!/usr/bin/env python3
"""Stage one observed OpenDART bulk-financial quarter without touching a DB.

Input is the read-only discovery JSON produced from the current official OpenDART
inventory. The script requires an exact BS/PL/CF/CE set for the requested period,
downloads only those observed file names, validates ZIP integrity/member paths and
basic TXT schema, and emits a SHA256 manifest.

It intentionally does not import data into SQLite. Database parsing is a separate
smoke stage using the pinned AlphaKRX ETL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import requests

MAIN_URL = "https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do"
LIST_URL = "https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/list.do"
DOWNLOAD_BASE = "https://opendart.fss.or.kr/cmm/downloadFnlttZip.do?fl_nm="
USER_AGENT = "KR-security-test/1.0 OpenDART bulk-financial staging"
TIMEOUT = 60
ROLES = ("BS", "PL", "CF", "CE")
EXPECTED_HEADER_MARKERS = (
    "재무제표종류",
    "종목코드",
    "회사명",
    "결산월",
    "결산기준일",
    "보고서종류",
    "항목코드",
    "항목명",
)
MAX_COMPRESSED_BYTES = 100 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 800 * 1024 * 1024


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--discovery-json", required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--quarter", type=int, choices=(1, 2, 3, 4), required=True)
    p.add_argument("--output", default="outputs/opendart_financial_stage")
    return p.parse_args()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_member(name: str) -> bool:
    p = PurePosixPath(name.replace("\\", "/"))
    return not p.is_absolute() and ".." not in p.parts


def select_inventory(discovery: dict, year: int, quarter: int):
    pattern = re.compile(
        rf"^{year}_{quarter}Q_(BS|PL|CF|CE)_(\d{{14}})\.zip$"
    )
    matches = []
    for row in discovery.get("inventory_records", []):
        filename = str(row.get("file_name") or "")
        m = pattern.match(filename)
        if not m:
            continue
        role = m.group(1)
        timestamp = m.group(2)
        if str(row.get("business_year")) != str(year):
            raise RuntimeError(f"inventory year mismatch for {filename}: {row}")
        matches.append({**row, "role": role, "timestamp": timestamp})

    by_role = {role: [r for r in matches if r["role"] == role] for role in ROLES}
    problems = {role: len(rows) for role, rows in by_role.items() if len(rows) != 1}
    if problems:
        raise RuntimeError(
            f"expected exactly one observed ZIP per role for {year} {quarter}Q; got {problems}"
        )
    selected = [by_role[role][0] for role in ROLES]
    doc_codes = {str(r.get("document_code")) for r in selected}
    if len(doc_codes) != 1:
        raise RuntimeError(f"mixed document codes: {doc_codes}")
    expected_doc = {1: "FQ", 2: "HY", 3: "FQ", 4: "AR"}.get(quarter)
    # OpenDART currently uses FQ for both Q1/Q3, HY for half-year and AR for annual.
    # If the site changes codes, fail closed and inspect rather than silently proceed.
    if expected_doc and doc_codes != {expected_doc}:
        raise RuntimeError(f"unexpected document code for {quarter}Q: {doc_codes} != {expected_doc}")
    return selected


def validate_zip(path: Path, role: str):
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_COMPRESSED_BYTES:
        raise RuntimeError(f"compressed size gate failed: {path} {path.stat().st_size}")
    if path.read_bytes()[:4] != b"PK\x03\x04":
        raise RuntimeError(f"ZIP signature missing: {path}")

    with zipfile.ZipFile(path, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {path.name}: {bad}")
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if not infos:
            raise RuntimeError(f"empty ZIP: {path.name}")
        if any(not safe_member(i.filename) for i in infos):
            raise RuntimeError(f"unsafe member path in {path.name}")
        txt_infos = [i for i in infos if i.filename.lower().endswith(".txt")]
        if not txt_infos:
            raise RuntimeError(f"no TXT members in {path.name}")
        total_uncompressed = sum(i.file_size for i in infos)
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise RuntimeError(
                f"uncompressed size gate failed: {path.name}: {total_uncompressed}"
            )

        headers = []
        for info in txt_infos:
            with zf.open(info) as f:
                first = f.readline(512 * 1024).decode("cp949", errors="replace").strip("\r\n")
            cols = first.split("\t")
            missing = [m for m in EXPECTED_HEADER_MARKERS if m not in cols]
            if missing:
                raise RuntimeError(
                    f"schema marker missing in {path.name}/{info.filename}: {missing}; first cols={cols[:20]}"
                )
            headers.append({
                "member": info.filename,
                "bytes": int(info.file_size),
                "columns": cols,
                "column_count": len(cols),
            })

        # Role-specific sanity: current OpenDART files put the statement number in
        # member names. This is diagnostic, not used to parse amounts.
        member_names = [i.filename for i in txt_infos]
        return {
            "member_count": len(infos),
            "txt_member_count": len(txt_infos),
            "uncompressed_bytes": total_uncompressed,
            "member_names": member_names,
            "headers": headers,
            "role": role,
        }


def main():
    a = parse_args()
    discovery_path = Path(a.discovery_json)
    discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
    if discovery.get("status") != "INVENTORY_DISCOVERED":
        raise RuntimeError(f"discovery is not usable: {discovery.get('status')}")

    selected = select_inventory(discovery, a.year, a.quarter)
    out = Path(a.output)
    zip_dir = out / "raw_financial"
    zip_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
        "Referer": MAIN_URL,
    })
    # Establish the same first-party session path used by the public page.
    session.get(MAIN_URL, timeout=TIMEOUT).raise_for_status()
    session.get(LIST_URL, timeout=TIMEOUT).raise_for_status()

    manifest_rows = []
    for row in selected:
        filename = row["file_name"]
        role = row["role"]
        url = DOWNLOAD_BASE + quote(filename, safe="/._-")
        response = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        target = zip_dir / filename
        target.write_bytes(response.content)
        audit = validate_zip(target, role)
        manifest_rows.append({
            "business_year": str(a.year),
            "quarter": int(a.quarter),
            "document_code": row.get("document_code"),
            "role": role,
            "file_name": filename,
            "inventory_timestamp": row["timestamp"],
            "source_row_text": row.get("row_text"),
            "download_url": url,
            "http_status": int(response.status_code),
            "content_type": response.headers.get("Content-Type"),
            "compressed_bytes": int(target.stat().st_size),
            "sha256": sha256_file(target),
            **audit,
        })

    roles = [r["role"] for r in manifest_rows]
    if roles != list(ROLES):
        raise RuntimeError(f"staged role order/set drift: {roles}")

    manifest = {
        "status": "STAGED_VALIDATED",
        "source_discovery_sha256": sha256_file(discovery_path),
        "year": a.year,
        "quarter": a.quarter,
        "roles": list(ROLES),
        "files": manifest_rows,
        "safety": {
            "mutates_database": False,
            "writes_only_staging_directory": True,
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": manifest["status"],
        "year": a.year,
        "quarter": a.quarter,
        "files": [
            {"role": r["role"], "file_name": r["file_name"], "bytes": r["compressed_bytes"], "sha256": r["sha256"]}
            for r in manifest_rows
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
