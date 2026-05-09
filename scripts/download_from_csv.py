#!/usr/bin/env python3
"""Download all UAP / PURSUE Release 01 files using the official war.gov CSV index."""
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "uap-csv.csv"
OUT_DIR = ROOT / "release_1_pdfs"
OUT_DIR.mkdir(exist_ok=True)
LOG = OUT_DIR / "_download.log"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36")
COMMON_HEADERS = [
    "-A", UA,
    "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "-H", "Accept-Language: en-US,en;q=0.5",
    "-H", "Accept-Encoding: gzip, deflate, br",
    "-H", "DNT: 1",
    "-H", "Connection: keep-alive",
    "-H", "Upgrade-Insecure-Requests: 1",
    "-H", "Sec-Fetch-Dest: document",
    "-H", "Sec-Fetch-Mode: navigate",
    "-H", "Sec-Fetch-Site: none",
    "-H", "Sec-Fetch-User: ?1",
    "-H", "Referer: https://www.war.gov/UFO/",
    "--compressed",
]


def log(msg):
    print(msg)
    with open(LOG, "a") as f:
        f.write(msg + "\n")


def download(url: str, out_path: Path) -> tuple[bool, int]:
    if out_path.exists() and out_path.stat().st_size > 1000:
        return True, out_path.stat().st_size
    cmd = ["curl", "-sL"] + COMMON_HEADERS + [
        "-w", "%{http_code}", "-o", str(out_path), url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    code = result.stdout.strip()
    size = out_path.stat().st_size if out_path.exists() else 0
    if code == "200" and size > 1000:
        # Verify file type
        ftype = subprocess.run(["file", "-b", str(out_path)], capture_output=True, text=True).stdout.strip()
        if "PDF" in ftype or "JPEG" in ftype or "PNG" in ftype or "MP4" in ftype or "Video" in ftype or "ISO Media" in ftype:
            return True, size
        else:
            out_path.unlink()
            return False, 0
    if out_path.exists():
        out_path.unlink()
    return False, 0


def main():
    LOG.write_text("")  # reset
    rows = []
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            url = row.get("PDF | Image Link", "").strip()
            if not url:
                continue
            rows.append({
                "title": row.get("Title", "").strip().replace("\n", " "),
                "type": row.get("Type", "").strip(),
                "agency": row.get("Agency", "").strip(),
                "release_date": row.get("Release Date", "").strip(),
                "incident_date": row.get("Incident Date", "").strip(),
                "incident_location": row.get("Incident Location", "").strip(),
                "description": row.get("Description Blurb", "").strip().replace("\n", " "),
                "url": url,
                "thumbnail": row.get("Modal Image", "").strip(),
                "video_pairing": row.get("Video Pairing", "").strip(),
                "pdf_pairing": row.get("PDF Pairing", "").strip(),
                "dvids_id": row.get("DVIDS Video ID", "").strip(),
            })

    log(f"Found {len(rows)} entries with URL in CSV")

    metadata = []
    ok = 0
    fail = 0
    for i, r in enumerate(rows, 1):
        url = r["url"]
        fname = os.path.basename(urlparse(url).path)
        out = OUT_DIR / fname
        success, size = download(url, out)
        r["filename"] = fname
        r["size_bytes"] = size
        r["downloaded"] = success
        metadata.append(r)
        prefix = "OK" if success else "FAIL"
        log(f"[{i:3d}/{len(rows)}] {prefix} {size:>12} {fname}")
        if success:
            ok += 1
        else:
            fail += 1

    # Write master metadata file
    meta_path = OUT_DIR / "_metadata.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    log("")
    log("=== Summary ===")
    log(f"Total: {len(rows)} | OK: {ok} | FAIL: {fail}")
    log(f"Metadata: {meta_path}")
    log(f"Output: {OUT_DIR}")


if __name__ == "__main__":
    main()
