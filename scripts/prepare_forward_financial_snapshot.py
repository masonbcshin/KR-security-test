#!/usr/bin/env python3
"""Prepare the signal-day financial raw-data tree for forward ETF shadow research.

The frozen AlphaKRX checkout remains the historical base snapshot. For the signal
calendar year, observed OpenDART bulk-financial ZIPs replace any same-year files
from that base. This prevents a stale upstream AlphaKRX data repository from
blocking forward PIT freshness while preserving the frozen AlphaKRX parser and
feature methodology.

This script never writes to a research SQLite DB. It only discovers/stages the
official OpenDART files, builds a composite raw-data directory, and emits a
cryptographic provenance manifest consumed by build_forward_research_db.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROLES = ("BS", "PL", "CF", "CE")
DOC_BY_QUARTER = {1: "FQ", 2: "HY", 3: "TQ", 4: "FY"}
STATUS = "FORWARD_FINANCIAL_SNAPSHOT_READY"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--signal-date", required=True, help="YYYYMMDD")
    p.add_argument("--base-data-root", required=True)
    p.add_argument("--base-data-sha", required=True)
    p.add_argument("--composite-data-root", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--discover-script", default="scripts/discover_opendart_bulk_financials.py")
    p.add_argument("--stage-script", default="scripts/stage_opendart_bulk_financials.py")
    return p.parse_args()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_year(name: str):
    m = re.match(r"^(\d{4})_", name)
    return int(m.group(1)) if m else None


def observed_quarters(discovery: dict, year: int):
    by_q: dict[int, list[dict]] = {}
    pattern = re.compile(rf"^{year}_([1-4])Q_(BS|PL|CF|CE)_(\d{{14}})\.zip$")
    for row in discovery.get("inventory_records", []):
        if str(row.get("business_year")) != str(year):
            continue
        filename = str(row.get("file_name") or "")
        m = pattern.match(filename)
        if not m:
            continue
        q = int(m.group(1))
        by_q.setdefault(q, []).append(row)

    complete = []
    for q, rows in sorted(by_q.items()):
        roles = [re.match(pattern, str(r.get("file_name") or "")).group(2) for r in rows]
        counts = {role: roles.count(role) for role in ROLES}
        if counts != {role: 1 for role in ROLES}:
            raise RuntimeError(f"partial/duplicate OpenDART inventory for {year}Q{q}: {counts}")
        doc_codes = {str(r.get("document_code")) for r in rows}
        if doc_codes != {DOC_BY_QUARTER[q]}:
            raise RuntimeError(
                f"unexpected OpenDART document code for {year}Q{q}: {doc_codes} != {DOC_BY_QUARTER[q]}"
            )
        complete.append(q)
    return complete


def link_or_copy(src: Path, dst: Path):
    try:
        os.link(src, dst)
        return "hardlink"
    except OSError:
        shutil.copy2(src, dst)
        return "copy"


def main():
    a = parse_args()
    if not re.fullmatch(r"\d{8}", a.signal_date):
        raise ValueError("--signal-date must be YYYYMMDD")
    if not re.fullmatch(r"[0-9a-f]{40}", a.base_data_sha):
        raise ValueError("--base-data-sha must be an exact 40-hex Git commit")

    signal_year = int(a.signal_date[:4])
    base_root = Path(a.base_data_root).resolve()
    base_raw = base_root / "data" / "raw_financial"
    if not base_raw.is_dir():
        raise FileNotFoundError(f"base raw financial directory missing: {base_raw}")

    out = Path(a.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    discovery_dir = out / "discovery"
    subprocess.run(
        [sys.executable, a.discover_script, "--output", str(discovery_dir)],
        check=True,
    )
    discovery_path = discovery_dir / "discovery.json"
    discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
    if discovery.get("status") != "INVENTORY_DISCOVERED":
        raise RuntimeError(f"OpenDART discovery unusable: {discovery.get('status')}")

    quarters = observed_quarters(discovery, signal_year)
    staged = []
    for q in quarters:
        stage_dir = out / f"opendart_{signal_year}q{q}"
        subprocess.run(
            [
                sys.executable,
                a.stage_script,
                "--discovery-json", str(discovery_path),
                "--year", str(signal_year),
                "--quarter", str(q),
                "--output", str(stage_dir),
            ],
            check=True,
        )
        manifest_path = stage_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "STAGED_VALIDATED":
            raise RuntimeError(f"staging manifest unusable for {signal_year}Q{q}")
        staged.append(
            {
                "quarter": q,
                "manifest_path": str(manifest_path),
                "manifest_sha256": sha256_file(manifest_path),
                "files": manifest["files"],
                "stage_dir": str(stage_dir),
            }
        )

    composite_root = Path(a.composite_data_root).resolve()
    if composite_root.exists():
        shutil.rmtree(composite_root)
    composite_raw = composite_root / "data" / "raw_financial"
    composite_raw.mkdir(parents=True, exist_ok=True)

    base_count = 0
    transfer_modes: dict[str, int] = {"hardlink": 0, "copy": 0}
    for src in sorted(base_raw.glob("*.zip")):
        if file_year(src.name) == signal_year:
            continue
        mode = link_or_copy(src, composite_raw / src.name)
        transfer_modes[mode] += 1
        base_count += 1

    supplement_files = []
    for stage in staged:
        stage_raw = Path(stage["stage_dir"]) / "raw_financial"
        for rec in stage["files"]:
            filename = rec["file_name"]
            src = stage_raw / filename
            dst = composite_raw / filename
            if dst.exists():
                raise RuntimeError(f"composite filename collision: {filename}")
            actual_sha = sha256_file(src)
            if actual_sha != rec["sha256"]:
                raise RuntimeError(
                    f"staged ZIP hash drift for {filename}: {actual_sha} != {rec['sha256']}"
                )
            mode = link_or_copy(src, dst)
            transfer_modes[mode] += 1
            supplement_files.append(
                {
                    "quarter": stage["quarter"],
                    "role": rec["role"],
                    "file_name": filename,
                    "sha256": actual_sha,
                    "bytes": int(src.stat().st_size),
                }
            )

    current_year_files = sorted(
        p.name for p in composite_raw.glob(f"{signal_year}_*.zip")
    )
    listed_names = sorted(x["file_name"] for x in supplement_files)
    if current_year_files != listed_names:
        raise RuntimeError(
            f"current-year provenance mismatch: composite={current_year_files} staged={listed_names}"
        )

    manifest = {
        "status": STATUS,
        "signal_date": a.signal_date,
        "signal_year": signal_year,
        "base_alphakrx_sha": a.base_data_sha,
        "base_raw_financial_dir": str(base_raw),
        "base_files_excluding_signal_year": base_count,
        "current_year_policy": "exclude all signal-year AlphaKRX raw ZIPs; use only same-run official OpenDART staged ZIPs",
        "official_source": "https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do",
        "discovery_json_sha256": sha256_file(discovery_path),
        "opendart_page_sha256": discovery.get("page_sha256"),
        "opendart_list_sha256": discovery.get("list_sha256"),
        "observed_complete_quarters": quarters,
        "staged_manifests": [
            {
                "quarter": s["quarter"],
                "manifest_sha256": s["manifest_sha256"],
                "manifest_path": s["manifest_path"],
            }
            for s in staged
        ],
        "supplement_files": supplement_files,
        "composite_data_root": str(composite_root),
        "composite_raw_financial_dir": str(composite_raw),
        "composite_zip_count": len(list(composite_raw.glob("*.zip"))),
        "transfer_modes": transfer_modes,
        "safety": {
            "mutates_research_database": False,
            "uses_open_dart_only_for_signal_year": True,
            "future_availability_is_not_trimmed": True,
        },
    }
    manifest_path = out / "forward_financial_snapshot_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
