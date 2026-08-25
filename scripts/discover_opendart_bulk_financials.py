#!/usr/bin/env python3
"""Read-only discovery probe for OpenDART financial bulk-download resources.

This script does NOT download/import financial ZIPs and does not touch the DB.
It snapshots the official page plus its current AJAX inventory and exposes the
observed download metadata. A later downloader may consume only this observed
inventory after separate review.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do"
LIST_URL = "https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/list.do"
DOWNLOAD_BASE = "https://opendart.fss.or.kr/cmm/downloadFnlttZip.do?fl_nm="
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


def parse_download_call(onclick: str):
    match = re.search(r"download_ext002\s*\((.*?)\)", onclick, flags=re.S)
    if not match:
        return None
    raw_args = match.group(1).strip()
    try:
        args = ast.literal_eval("(" + raw_args + ("," if "," not in raw_args else "") + ")")
    except (ValueError, SyntaxError):
        return {"raw_args": raw_args, "parse_error": True}
    if not isinstance(args, tuple):
        args = (args,)
    values = [str(x) for x in args]
    rec = {"raw_args": raw_args, "args": values, "parse_error": False}
    if len(values) >= 4:
        rec.update({
            "business_year": values[0],
            "document_code": values[1],
            "role_code": values[2],
            "file_name": values[3],
            "download_url_not_requested": DOWNLOAD_BASE + quote(values[3], safe="/._-"),
        })
    return rec


def main():
    args = parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
        "Referer": SOURCE_URL,
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
                    if href and not href.lower().startswith("javascript:") else None
                ),
                "onclick": onclick,
                "literals": literals(onclick),
            })

    inline_scripts = []
    script_sources = []
    for index, tag in enumerate(soup.find_all("script")):
        src = clean_text(tag.get("src"))
        if src:
            script_sources.append({"index": index, "src": src, "absolute_src": urljoin(SOURCE_URL, src)})
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

    direct_count = sum(1 for a in anchors if a["onclick"] or relevant(a["href"])) + len(inline_scripts)
    external_scripts = []
    if direct_count == 0:
        host = urlparse(SOURCE_URL).netloc
        attempts = 0
        for item in script_sources:
            absolute = item["absolute_src"]
            if urlparse(absolute).netloc != host or attempts >= MAX_EXTERNAL_SCRIPT_ATTEMPTS:
                continue
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

    # Current page JS calls this endpoint on document-ready. Fetch it read-only
    # and parse only the download callback arguments; do not request the ZIP URL.
    list_response = session.get(LIST_URL, timeout=PAGE_TIMEOUT)
    list_response.raise_for_status()
    if not list_response.encoding or list_response.encoding.lower() == "iso-8859-1":
        list_response.encoding = list_response.apparent_encoding
    list_html = list_response.text
    (out / "list.html").write_bytes(list_response.content)
    list_soup = BeautifulSoup(list_html, "html.parser")
    inventory = []
    for row_index, row in enumerate(list_soup.find_all("tr")):
        row_text = clean_text(row.get_text(" ", strip=True))
        row_name = clean_text(row.get("name"))
        for link_index, link in enumerate(row.find_all("a")):
            onclick = clean_text(link.get("onclick"))
            parsed = parse_download_call(onclick)
            if parsed is None:
                continue
            inventory.append({
                "row_index": row_index,
                "link_index": link_index,
                "row_name": row_name,
                "row_text": row_text,
                "link_text": clean_text(link.get_text(" ", strip=True)),
                "onclick": onclick,
                **parsed,
            })

    candidates = []
    for row in anchors:
        if row["onclick"] or relevant(row["href"]):
            candidates.append({"source": "anchor", **row})
    for row in inline_scripts:
        candidates.append({"source": "inline_script", **row})
    for row in external_scripts:
        if row.get("relevant"):
            candidates.append({"source": "external_script", **row})

    years = sorted({r.get("business_year") for r in inventory if r.get("business_year")}, reverse=True)
    result = {
        "source_url": SOURCE_URL,
        "list_url": LIST_URL,
        "http_status": int(response.status_code),
        "list_http_status": int(list_response.status_code),
        "content_type": response.headers.get("Content-Type"),
        "page_sha256": sha256_bytes(raw),
        "list_sha256": sha256_bytes(list_response.content),
        "page_bytes": len(raw),
        "list_bytes": len(list_response.content),
        "expected_marker_found": True,
        "anchor_records": anchors,
        "forms": forms,
        "script_sources": script_sources,
        "inline_script_records": inline_scripts,
        "external_script_records": external_scripts,
        "candidate_records": candidates,
        "inventory_records": inventory,
        "inventory_count": len(inventory),
        "business_years": years,
        "latest_business_year": years[0] if years else None,
        "status": "INVENTORY_DISCOVERED" if inventory else "DOWNLOAD_CALLBACK_NOT_FOUND",
        "safety": {
            "downloads_financial_zip": False,
            "mutates_database": False,
            "weakens_pit_freshness_gate": False,
        },
    }
    (out / "discovery.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "source_url": SOURCE_URL,
        "http_status": result["http_status"],
        "list_http_status": result["list_http_status"],
        "page_sha256": result["page_sha256"],
        "list_sha256": result["list_sha256"],
        "inventory_count": result["inventory_count"],
        "business_years": result["business_years"],
        "latest_business_year": result["latest_business_year"],
        "status": result["status"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
