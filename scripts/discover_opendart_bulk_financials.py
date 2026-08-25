#!/usr/bin/env python3
"""Read-only discovery probe for OpenDART financial bulk-download resources.

This script intentionally does NOT download or import financial ZIP files and does
not mutate the research database. It snapshots the official OpenDART bulk-download
page and records only the link/callback/script metadata needed to build a later,
separately reviewed downloader.

Why discovery first:
- the public page is the official source, but its download inventory is not exposed
  as a documented OpenAPI endpoint;
- blindly hard-coding a legacy onclick/download URL would be brittle and could
  silently fetch the wrong quarter;
- the PIT freshness guard must never be bypassed simply because discovery fails.
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
TIMEOUT = 30
MAX_SAME_ORIGIN_SCRIPTS = 30

KEYWORDS = (
    "download",
    "dwld",
    "file",
    "zip",
    "fnltt",
    "재무",
    "사업보고서",
    "분기보고서",
    "반기보고서",
)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="outputs/opendart_bulk_discovery")
    return p.parse_args()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean_text(x: str | None) -> str:
    return re.sub(r"\s+", " ", (x or "")).strip()


def relevant(text: str) -> bool:
    lo = text.lower()
    return any(k.lower() in lo for k in KEYWORDS)


def extract_string_literals(text: str):
    # Diagnostic only: identify URL/path/ZIP-looking literals without executing JS.
    out = set()
    for quote, value in re.findall(r"(['\"])(.{1,500}?)\1", text, flags=re.S):
        v = clean_text(value)
        lo = v.lower()
        if (
            ".zip" in lo
            or "download" in lo
            or "dwld" in lo
            or "fnltt" in lo
            or v.startswith("/")
        ):
            out.add(v)
    return sorted(out)


def main():
    a = parse_args()
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7"})
    resp = session.get(SOURCE_URL, timeout=TIMEOUT)
    resp.raise_for_status()
    raw = resp.content
    # requests generally detects UTF-8 here, but OpenDART has historically served
    # Korean pages with varying declarations. apparent_encoding is safer for audit.
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding
    html = resp.text
    if EXPECTED_MARKER not in html:
        raise RuntimeError(f"official page marker missing: {EXPECTED_MARKER}")

    (out / "page.html").write_bytes(raw)
    soup = BeautifulSoup(html, "html.parser")

    anchors = []
    for idx, tag in enumerate(soup.find_all("a")):
        href = clean_text(tag.get("href"))
        onclick = clean_text(tag.get("onclick"))
        text = clean_text(tag.get_text(" ", strip=True))
        combined = " ".join((href, onclick, text))
        if relevant(combined) or onclick:
            anchors.append({
                "index": idx,
                "text": text,
                "href": href,
                "absolute_href": urljoin(SOURCE_URL, href) if href and not href.lower().startswith("javascript:") else None,
                "onclick": onclick,
                "literals": extract_string_literals(onclick),
            })

    inline_scripts = []
    external_scripts = []
    base_host = urlparse(SOURCE_URL).netloc
    script_tags = soup.find_all("script")
    fetched = 0
    for idx, tag in enumerate(script_tags):
        src = clean_text(tag.get("src"))
        body = tag.string or tag.get_text("\n") or ""
        if src:
            absolute = urljoin(SOURCE_URL, src)
            rec = {"index": idx, "src": src, "absolute_src": absolute}
            if urlparse(absolute).netloc == base_host and fetched < MAX_SAME_ORIGIN_SCRIPTS:
                try:
                    r = session.get(absolute, timeout=TIMEOUT)
                    rec["http_status"] = int(r.status_code)
                    if r.ok:
                        fetched += 1
                        text = r.text
                        rec["sha256"] = sha256_bytes(r.content)
                        rec["bytes"] = len(r.content)
                        rec["relevant"] = relevant(text)
                        if rec["relevant"]:
                            lines = text.splitlines()
                            snippets = []
                            for line_no, line in enumerate(lines, start=1):
                                if relevant(line):
                                    snippets.append({"line": line_no, "text": clean_text(line)[:1200]})
                                if len(snippets) >= 80:
                                    break
                            rec["relevant_snippets"] = snippets
                            rec["literals"] = extract_string_literals(text)
                except requests.RequestException as exc:
                    rec["fetch_error"] = f"{type(exc).__name__}: {exc}"
            external_scripts.append(rec)
        elif body and relevant(body):
            inline_scripts.append({
                "index": idx,
                "sha256": sha256_bytes(body.encode("utf-8")),
                "literals": extract_string_literals(body),
                "snippets": [
                    {"line": i, "text": clean_text(line)[:1200]}
                    for i, line in enumerate(body.splitlines(), start=1)
                    if relevant(line)
                ][:120],
            })

    forms = []
    for idx, form in enumerate(soup.find_all("form")):
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
            "index": idx,
            "action": action,
            "absolute_action": urljoin(SOURCE_URL, action) if action else SOURCE_URL,
            "method": method,
            "fields": fields,
        })

    direct_candidates = []
    for arow in anchors:
        if arow["onclick"] or (arow["href"] and relevant(arow["href"])):
            direct_candidates.append({"source": "anchor", **arow})
    for srow in inline_scripts:
        if srow.get("literals") or srow.get("snippets"):
            direct_candidates.append({"source": "inline_script", **srow})
    for srow in external_scripts:
        if srow.get("relevant"):
            direct_candidates.append({"source": "external_script", **srow})

    result = {
        "source_url": SOURCE_URL,
        "http_status": int(resp.status_code),
        "content_type": resp.headers.get("Content-Type"),
        "page_sha256": sha256_bytes(raw),
        "page_bytes": len(raw),
        "expected_marker_found": True,
        "anchor_records": anchors,
        "forms": forms,
        "inline_script_records": inline_scripts,
        "external_script_records": external_scripts,
        "candidate_records": direct_candidates,
        "candidate_count": len(direct_candidates),
        "status": "DISCOVERY_METADATA_FOUND" if direct_candidates else "NO_DOWNLOAD_METADATA_FOUND",
        "safety": {
            "downloads_financial_zip": False,
            "mutates_database": False,
            "weakens_pit_freshness_gate": False,
        },
    }
    (out / "discovery.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Compact stdout for CI inspection without dumping the full page.
    compact = {
        "source_url": result["source_url"],
        "http_status": result["http_status"],
        "page_sha256": result["page_sha256"],
        "anchors": len(anchors),
        "forms": len(forms),
        "inline_relevant_scripts": len(inline_scripts),
        "external_scripts": len(external_scripts),
        "candidate_count": len(direct_candidates),
        "status": result["status"],
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
