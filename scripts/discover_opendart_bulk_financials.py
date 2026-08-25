#!/usr/bin/env python3
"""Read-only discovery probe for OpenDART financial bulk-download resources.

This script does NOT download/import financial ZIPs and does not touch the DB.
It snapshots the official page and exposes current link/callback metadata so a
later downloader can be built from observed current behavior rather than a
hard-coded legacy URL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do"
EXPECTED_MARKER = "재무정보 일괄다운로드"
USER_AGENT = "KR-security-test/1.0 OpenDART bulk-financial discovery (read-only)"
PAGE_TIMEOUT = 20
SCRIPT_TIMEOUT = 3
MAX_EXTERNAL_SCRIPT_ATTEMPTS = 8

KEYWORDS = (
    "download", "dwld", "file", "zip", "fnltt",
    "재무", "사업보고서", "분기보고서", "반기보고서",
)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="outputs/opendart_bulk_discovery")
    return p.parse_args()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def relevant(text: str) -> bool:
    lo = text.lower()
    return any(k.lower() in lo for k in KEYWORDS)


def literals(text: str):
    found = set()
    for _, value in re.findall(r"(['\"])(.{1,500}?)\1", text, flags=re.S):
        v = clean_text(value)
        lo = v.lower()
        if ".zip" in lo or "download" in lo or "dwld" in lo or "fnltt" in lo or v.startswith("/"):
            found.add(v)
    return sorted(found)


def relevant_lines(text: str, limit: int = 80):
    rows = []
    for number, line in enumerate(text.splitlines(), start=1):
        if relevant(line):
            rows.append({"line": number, "text": clean_text(line)[:1200]})
            if len(rows) >= limit:
                break
    return rows


def main():
    args = parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
    })
    response = session.get(SOURCE_URL, timeout=PAGE_TIMEOUT)
    response.raise_for_status()
    raw = response.content
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding
    html = response.text
    if EXPECTED_MARKER not in html:
        raise RuntimeError(f"official page marker missing: {EXPECTED_MARKER}")
    (out / "page.html").write_bytes(raw)

    soup = BeautifulSoup(html, "html.parser")
    anchors = []
    for index, tag in enumerate(soup.find_all("a")):
        href = clean_text(tag.get("href"))
        onclick = clean_text(tag.get("onclick"))
        text = clean_text(tag.get_text(" ", strip=True))
        if onclick or relevant(" ".join((href, text))):
            anchors.append({
                "index": index,
                "text": text,
                "href": href,
                "absolute_href": (
                    urljoin(SOURCE_URL, href)
                    if href and not href.lower().startswith("javascript:")
                    else None
                ),
                "onclick": onclick,
                "literals": literals(onclick),
            })

    inline_scripts = []
    script_sources = []
    for index, tag in enumerate(soup.find_all("script")):
        src = clean_text(tag.get("src"))
        if src:
            script_sources.append({
                "index": index,
                "src": src,
                "absolute_src": urljoin(SOURCE_URL, src),
            })
            continue
        body = tag.string or tag.get_text("\n") or ""
        rows = relevant_lines(body)
        lits = literals(body)
        if rows or lits:
            inline_scripts.append({
                "index": index,
                "sha256": sha256_bytes(body.encode("utf-8")),
                "literals": lits,
                "snippets": rows,
            })

    forms = []
    for index, form in enumerate(soup.find_all("form")):
        action = clean_text(form.get("action"))
        method = clean_text(form.get("method") or "GET").upper()
        fields = []
        for field in form.find_all(["input", "select", "textarea", "button"]):
            fields.append({
                "tag": field.name,
                "name": clean_text(field.get("name")),
                "value": clean_text(field.get("value")),
                "type": clean_text(field.get("type")),
            })
        forms.append({
            "index": index,
            "action": action,
            "absolute_action": urljoin(SOURCE_URL, action) if action else SOURCE_URL,
            "method": method,
            "fields": fields,
        })

    # If the current HTML already exposes callbacks/inline metadata, do not fan
    # out across common site JS. Otherwise inspect a strictly bounded sample of
    # same-origin scripts. Discovery must remain cheap and non-invasive.
    direct_count = sum(1 for a in anchors if a["onclick"] or relevant(a["href"])) + len(inline_scripts)
    external_scripts = []
    if direct_count == 0:
        host = urlparse(SOURCE_URL).netloc
        attempts = 0
        for item in script_sources:
            absolute = item["absolute_src"]
            if urlparse(absolute).netloc != host:
                continue
            if attempts >= MAX_EXTERNAL_SCRIPT_ATTEMPTS:
                break
            attempts += 1
            rec = dict(item)
            try:
                r = session.get(absolute, timeout=SCRIPT_TIMEOUT)
                rec["http_status"] = int(r.status_code)
                if r.ok:
                    rows = relevant_lines(r.text)
                    lits = literals(r.text)
                    rec.update({
                        "sha256": sha256_bytes(r.content),
                        "bytes": len(r.content),
                        "relevant": bool(rows or lits),
                        "relevant_snippets": rows,
                        "literals": lits,
                    })
            except requests.RequestException as exc:
                rec["fetch_error"] = f"{type(exc).__name__}: {exc}"
            external_scripts.append(rec)

    candidates = []
    for row in anchors:
        if row["onclick"] or relevant(row["href"]):
            candidates.append({"source": "anchor", **row})
    for row in inline_scripts:
        candidates.append({"source": "inline_script", **row})
    for row in external_scripts:
        if row.get("relevant"):
            candidates.append({"source": "external_script", **row})

    result = {
        "source_url": SOURCE_URL,
        "http_status": int(response.status_code),
        "content_type": response.headers.get("Content-Type"),
        "page_sha256": sha256_bytes(raw),
        "page_bytes": len(raw),
        "expected_marker_found": True,
        "anchor_records": anchors,
        "forms": forms,
        "script_sources": script_sources,
        "inline_script_records": inline_scripts,
        "external_script_records": external_scripts,
        "candidate_records": candidates,
        "candidate_count": len(candidates),
        "status": "DISCOVERY_METADATA_FOUND" if candidates else "NO_DOWNLOAD_METADATA_FOUND",
        "safety": {
            "downloads_financial_zip": False,
            "mutates_database": False,
            "weakens_pit_freshness_gate": False,
        },
    }
    (out / "discovery.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "source_url": SOURCE_URL,
        "http_status": result["http_status"],
        "page_sha256": result["page_sha256"],
        "anchors": len(anchors),
        "forms": len(forms),
        "script_sources": len(script_sources),
        "inline_relevant_scripts": len(inline_scripts),
        "external_scripts_attempted": len(external_scripts),
        "candidate_count": len(candidates),
        "status": result["status"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
