#!/usr/bin/env python3
"""Build dataset_index.json for the side-by-side viewer."""
import json, csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "dataset_index.json"
PROCESSED = ROOT / "mimo_processed"
PDFS = ROOT / "release_1_pdfs"
CSV_PATH = ROOT / "uap-csv.csv"

csv_meta_by_stem = {}
if CSV_PATH.exists():
    with CSV_PATH.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            link = (row.get("PDF | Image Link") or "").strip()
            if not link:
                continue
            stem = link.rstrip("/").split("/")[-1].rsplit(".", 1)[0]
            csv_meta_by_stem[stem] = {
                "title": (row.get("Title") or "").strip(),
                "agency": (row.get("Agency") or "").strip(),
                "incident_date": (row.get("Incident Date") or "").strip(),
                "incident_location": (row.get("Incident Location") or "").strip(),
                "release_date": (row.get("Release Date") or "").strip(),
                "type": (row.get("Type") or "").strip(),
                "blurb": (row.get("Description Blurb") or "").strip(),
                "source_link": link,
            }

records = []
for pdf in sorted(PDFS.glob("*.pdf")):
    stem = pdf.stem
    pdf_dir = PROCESSED / stem
    meta_path = pdf_dir / "_meta.json"
    if not meta_path.exists():
        continue
    meta = json.loads(meta_path.read_text())

    page_status = {}
    for p in meta.get("page_results", []):
        page_status[p["page"]] = p.get("status", "unknown")

    rejected_pages = sorted(int(f.name.split("_")[1].split(".")[0]) for f in pdf_dir.glob("*.rejected"))
    resolved_pages = sorted(int(f.name.split("_")[1].split(".")[0]) for f in pdf_dir.glob("*.resolved*"))
    error_pages = sorted(int(f.name.split("_")[1].split(".")[0]) for f in pdf_dir.glob("*.error"))

    page_md_chars = []
    for i in range(meta["total_pages"]):
        md = pdf_dir / f"page_{i+1:03d}.md"
        if md.exists():
            page_md_chars.append(md.stat().st_size)
        else:
            page_md_chars.append(0)

    csv_extra = csv_meta_by_stem.get(stem, {})

    records.append({
        "stem": stem,
        "file": meta["file"],
        "total_pages": meta["total_pages"],
        "size_bytes": meta["size_bytes"],
        "sha256": meta["sha256"],
        "source_url": meta["source_url_pattern"].format(filename=meta["file"]),
        "vlm_model": meta["vlm_model"],
        "vlm_prompt_version": meta["vlm_prompt_version"],
        "vlm_dpi": meta["vlm_dpi"],
        "rejected_then_resolved_pages": resolved_pages,
        "rejected_pages": rejected_pages,
        "error_pages": error_pages,
        "page_md_chars": page_md_chars,
        "title": csv_extra.get("title", stem),
        "agency": csv_extra.get("agency", ""),
        "incident_date": csv_extra.get("incident_date", ""),
        "incident_location": csv_extra.get("incident_location", ""),
        "release_date": csv_extra.get("release_date", "2026-05-08"),
        "type": csv_extra.get("type", ""),
        "blurb": csv_extra.get("blurb", ""),
    })

OUT.write_text(json.dumps({
    "version": "1.0",
    "generated_at": meta.get("completed_at"),
    "total_pdfs": len(records),
    "total_pages": sum(r["total_pages"] for r in records),
    "release": "PURSUE Release 01",
    "release_date": "2026-05-08",
    "source": "https://www.war.gov/medialink/ufo/",
    "records": records,
}, indent=2, ensure_ascii=False))
print(f"Wrote {OUT}: {len(records)} PDFs, {sum(r['total_pages'] for r in records)} pages")
