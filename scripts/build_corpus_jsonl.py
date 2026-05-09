#!/usr/bin/env python3
"""Build corpus.jsonl: one JSON record per page across all extracted PDFs.

Joins:
  mimo_processed/<stem>/page_NNN.md       → text, image_tags
  mimo_processed/<stem>/_meta.json        → provenance (sha256, vlm_model, ...)
  image_audit/recheck/<stem>/page_NNN.json → audit score + categories
  image_audit/fallback_mini/<stem>/page_NNN.json → image_tag_source flag
  web/data.json                           → record-level cleaned metadata
"""

from __future__ import annotations
import re, json
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "mimo_processed"
AUDIT = ROOT / "image_audit" / "recheck"
FALLBACK = ROOT / "image_audit" / "fallback_mini"
RENDERS = ROOT / "release_1_renders"
DATA_JSON = ROOT / "web" / "data.json"
OUT_PATH = ROOT / "corpus.jsonl"

IMG_RE = re.compile(r'\*Image:\s*(.+?)\*', re.DOTALL)


def derive_record_type(record: dict) -> str:
    title = (record.get("title") or "").lower()
    type_field = (record.get("type") or "").lower()
    if "mp4" in type_field or "video" in type_field:
        return "imagery"
    if ("image" in type_field or "photo" in type_field
        or "image" in title or "photo" in title):
        return "photo"
    if "mission report" in title:
        return "mission_report"
    if "cable" in title:
        return "cable"
    if "transcript" in title:
        return "transcript"
    if "summary" in title:
        return "summary"
    if "62-hq-83894" in title or "case file" in title:
        return "case_file"
    if "report" in title:
        return "report"
    return "other"


def stem_from_pdf_url(url: str) -> str | None:
    if not url:
        return None
    name = url.rstrip("/").split("/")[-1]
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return name.lower() if name else None


def main():
    # 1. Index web/data.json by candidate pdf_stem
    data = json.loads(DATA_JSON.read_text())
    events = data.get("events", [])
    by_stem = {}
    for ev in events:
        url = ev.get("pdf_url") or ""
        stem = stem_from_pdf_url(url)
        if stem:
            by_stem[stem] = ev
        title_stem = ev.get("title", "").lower()
        if title_stem and title_stem not in by_stem:
            by_stem[title_stem] = ev

    # 2. Index audit + fallback by (stem_lower, page_num)
    audit_idx = {}
    for stem_dir in AUDIT.iterdir() if AUDIT.exists() else []:
        if not stem_dir.is_dir():
            continue
        for jp in stem_dir.glob("page_*.json"):
            try:
                r = json.loads(jp.read_text())
            except Exception:
                continue
            audit_idx[(stem_dir.name.lower(), r.get("page_num"))] = r

    fallback_idx = {}
    for stem_dir in FALLBACK.iterdir() if FALLBACK.exists() else []:
        if not stem_dir.is_dir():
            continue
        for jp in stem_dir.glob("page_*.json"):
            try:
                r = json.loads(jp.read_text())
            except Exception:
                continue
            if r.get("status") == "ok":
                fallback_idx[(stem_dir.name.lower(), r.get("page_num"))] = r

    # 3. Walk mimo_processed and emit one record per page
    n_pages = 0
    n_with_image = 0
    n_replaced = 0
    n_skipped_no_meta = 0
    n_with_render = 0

    with OUT_PATH.open("w", encoding="utf-8") as out:
        for pdf_dir in sorted(PROCESSED.iterdir()):
            if not pdf_dir.is_dir():
                continue
            meta_path = pdf_dir / "_meta.json"
            if not meta_path.exists():
                n_skipped_no_meta += 1
                continue
            try:
                meta = json.loads(meta_path.read_text())
            except Exception:
                n_skipped_no_meta += 1
                continue

            stem = pdf_dir.name
            stem_lower = stem.lower()

            # Lookup in metadata index
            ev = by_stem.get(stem_lower)
            if ev is None:
                # try title-based search
                for k, v in by_stem.items():
                    if stem_lower in k or k in stem_lower:
                        ev = v
                        break

            agency = (ev or {}).get("agency", "")
            record_type = derive_record_type(ev or {"title": stem, "type": ""})
            title = (ev or {}).get("title", stem)
            location = (ev or {}).get("location_name") or None
            if location == "N/A":
                location = None

            render_dir = RENDERS / stem
            render_meta_path = render_dir / "_meta.json"
            render_meta = None
            if render_meta_path.exists():
                try:
                    render_meta = json.loads(render_meta_path.read_text())
                except Exception:
                    render_meta = None

            for md in sorted(pdf_dir.glob("page_*.md")):
                try:
                    page_num = int(md.name.split("_")[1].split(".")[0])
                except Exception:
                    continue
                text = md.read_text(encoding="utf-8", errors="replace")
                tags = [m.group(1).strip() for m in IMG_RE.finditer(text)]

                page_image_path = None
                page_image_format = None
                if render_dir.exists():
                    for ext in (".jpg", ".jpeg", ".png"):
                        cand = render_dir / f"page_{page_num:03d}{ext}"
                        if cand.exists():
                            page_image_path = f"release_1_renders/{stem}/{cand.name}"
                            # normalize ".jpeg" → "jpeg" (matches schema enum)
                            page_image_format = "jpeg" if ext == ".jpg" else ext.lstrip(".")
                            break

                fallback = fallback_idx.get((stem_lower, page_num))
                if fallback:
                    image_tag_source = "gpt-5.4-mini-2026"
                    n_replaced += 1
                else:
                    image_tag_source = "mimo-v2.5"

                audit = audit_idx.get((stem_lower, page_num))
                audit_score = None
                audit_cats = None
                if audit and fallback:
                    audit_score = (audit.get("judge") or {}).get("score")
                    audit_cats = audit.get("categories")

                rec = {
                    "record_id": stem,
                    "pdf_stem": stem,
                    "page_num": page_num,
                    "total_pages": meta.get("total_pages"),
                    "text": text,
                    "text_chars": len(text),
                    "image_tags": tags,
                    "image_tag_source": image_tag_source,
                    "image_tag_audit_score": audit_score,
                    "image_tag_audit_categories": audit_cats,
                    "source_url": meta.get("source_url_pattern", "").replace("{filename}", meta.get("file", "")),
                    "sha256": meta.get("sha256"),
                    "file_size_bytes": meta.get("size_bytes"),
                    "agency": agency,
                    "record_type": record_type,
                    "title": title,
                    "incident_location": location,
                    "incident_location_corrected": bool((ev or {}).get("location_fixed")),
                    "incident_date_iso": (ev or {}).get("date_iso"),
                    "year": (ev or {}).get("year"),
                    "year_inferred": bool((ev or {}).get("year_inferred")),
                    "incident_date_corrected": bool((ev or {}).get("date_fixed")),
                    "description_blurb": (ev or {}).get("description"),
                    "dvids_video_id": (ev or {}).get("dvids_id"),
                    "vlm_model": meta.get("vlm_model"),
                    "vlm_prompt_version": meta.get("vlm_prompt_version"),
                    "vlm_dpi": meta.get("vlm_dpi"),
                    "extraction_completed_at": meta.get("completed_at"),
                    "page_image_path": page_image_path,
                    "page_image_format": page_image_format,
                    "render_dpi": (render_meta or {}).get("render_dpi"),
                    "render_max_dim": (render_meta or {}).get("render_max_dim"),
                    "render_jpeg_quality": (render_meta or {}).get("render_jpeg_quality"),
                    "render_version": (render_meta or {}).get("render_version"),
                }
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_pages += 1
                if tags:
                    n_with_image += 1
                if page_image_path:
                    n_with_render += 1

    print(f"Wrote {OUT_PATH}")
    print(f"  pages: {n_pages}")
    print(f"  pages with image_tags: {n_with_image}")
    print(f"  pages with gpt-mini re-described tags: {n_replaced}")
    print(f"  pages with rendered page image: {n_with_render}")
    print(f"  pdfs skipped (no _meta.json): {n_skipped_no_meta}")


if __name__ == "__main__":
    main()
