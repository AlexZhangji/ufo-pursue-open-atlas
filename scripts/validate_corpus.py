#!/usr/bin/env python3
"""Schema-validate corpus.jsonl against schema.md.

Confirms every line:
  - parses as JSON
  - has the always-present fields with the right Python type (or None
    where nullable)
  - enums (image_tag_source, agency, record_type) are within the
    declared value sets

Exit code 0 if every record is valid, 1 if any record fails. Prints
a per-error summary plus an aggregate count at the end so a single
malformed line does not drown the report.

Run from the repo root:
    python scripts/validate_corpus.py
"""

from __future__ import annotations
import json, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus.jsonl"

# field -> (allowed Python types, nullable?)
SCHEMA: dict[str, tuple[tuple[type, ...], bool]] = {
    "record_id": ((str,), False),
    "pdf_stem": ((str,), False),
    "page_num": ((int,), False),
    "total_pages": ((int,), True),  # null if upstream meta missing
    "text": ((str,), False),
    "text_chars": ((int,), False),
    "image_tags": ((list,), False),
    "image_tag_source": ((str,), False),
    "image_tag_audit_score": ((int,), True),
    "image_tag_audit_categories": ((list,), True),
    "source_url": ((str,), False),
    "sha256": ((str,), True),  # null if upstream meta missing
    "file_size_bytes": ((int,), True),
    "agency": ((str,), False),
    "record_type": ((str,), False),
    "title": ((str,), False),
    "incident_location": ((str,), True),
    "incident_location_corrected": ((bool,), False),
    "incident_date_iso": ((str,), True),
    "year": ((int,), True),
    "year_inferred": ((bool,), False),
    "incident_date_corrected": ((bool,), False),
    "description_blurb": ((str,), True),
    "dvids_video_id": ((str,), True),
    "vlm_model": ((str,), True),
    "vlm_prompt_version": ((str,), True),
    "vlm_dpi": ((int,), True),
    "extraction_completed_at": ((str,), True),
    "page_image_path": ((str,), True),
    "page_image_format": ((str,), True),
    "render_dpi": ((int,), True),
    "render_max_dim": ((int,), True),
    "render_jpeg_quality": ((int,), True),
    "render_version": ((str,), True),
}

ENUM_AGENCY = {"Department of War", "Department of State", "FBI", "NASA", ""}
ENUM_IMAGE_TAG_SOURCE = {"mimo-v2.5", "gpt-5.4-mini-2026"}
ENUM_RECORD_TYPE = {"mission_report", "cable", "case_file", "photo",
                    "imagery", "report", "summary", "transcript", "other"}
ENUM_IMAGE_FORMAT = {"jpeg", "jpg", "png"}


def validate_record(rec: dict, lineno: int) -> list[str]:
    errors: list[str] = []
    for field, (types, nullable) in SCHEMA.items():
        if field not in rec:
            errors.append(f"line {lineno}: missing field '{field}'")
            continue
        v = rec[field]
        if v is None:
            if not nullable:
                errors.append(f"line {lineno}: '{field}' is null but field is non-nullable")
            continue
        # bool is a subclass of int; check bool *before* int to keep them distinct
        if bool in types and isinstance(v, bool):
            continue
        if isinstance(v, bool) and bool not in types:
            errors.append(
                f"line {lineno}: '{field}' is bool, expected {[t.__name__ for t in types]}")
            continue
        if not isinstance(v, types):
            errors.append(
                f"line {lineno}: '{field}' is {type(v).__name__}, "
                f"expected {[t.__name__ for t in types]}")

    # Enum checks (only if present and non-null)
    if rec.get("image_tag_source") not in ENUM_IMAGE_TAG_SOURCE:
        errors.append(
            f"line {lineno}: image_tag_source={rec.get('image_tag_source')!r} "
            f"not in {ENUM_IMAGE_TAG_SOURCE}")
    if rec.get("record_type") not in ENUM_RECORD_TYPE:
        errors.append(
            f"line {lineno}: record_type={rec.get('record_type')!r} "
            f"not in {ENUM_RECORD_TYPE}")
    agency = rec.get("agency")
    if agency is not None and agency not in ENUM_AGENCY:
        errors.append(
            f"line {lineno}: agency={agency!r} not in {ENUM_AGENCY}")
    fmt = rec.get("page_image_format")
    if fmt is not None and fmt not in ENUM_IMAGE_FORMAT:
        errors.append(
            f"line {lineno}: page_image_format={fmt!r} not in {ENUM_IMAGE_FORMAT}")

    # Cross-field invariants
    if rec.get("page_image_path") and not rec.get("page_image_format"):
        errors.append(
            f"line {lineno}: page_image_path is set but page_image_format is null")
    if rec.get("text_chars") is not None and rec.get("text") is not None:
        if rec["text_chars"] != len(rec["text"]):
            errors.append(
                f"line {lineno}: text_chars={rec['text_chars']} "
                f"!= len(text)={len(rec['text'])}")

    return errors


def main():
    if not CORPUS.exists():
        print(f"ERROR: {CORPUS} not found", file=sys.stderr)
        sys.exit(1)

    n_total = 0
    n_valid = 0
    error_count_by_kind: Counter[str] = Counter()
    sample_errors: list[str] = []
    pages_with_render = 0
    by_agency: Counter[str] = Counter()
    by_record_type: Counter[str] = Counter()

    with CORPUS.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            n_total += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                error_count_by_kind["json-parse"] += 1
                if len(sample_errors) < 20:
                    sample_errors.append(f"line {lineno}: JSON parse error: {e}")
                continue

            errors = validate_record(rec, lineno)
            if errors:
                for e in errors:
                    kind = e.split(":", 2)[-1].strip().split()[0]
                    error_count_by_kind[kind] += 1
                    if len(sample_errors) < 20:
                        sample_errors.append(e)
            else:
                n_valid += 1
                if rec.get("page_image_path"):
                    pages_with_render += 1
                by_agency[rec.get("agency") or "(empty)"] += 1
                by_record_type[rec.get("record_type") or "(empty)"] += 1

    print(f"corpus.jsonl: {n_total} records, {n_valid} valid")
    print(f"  pages with rendered image: {pages_with_render}")
    print(f"  by agency: {dict(by_agency.most_common())}")
    print(f"  by record_type: {dict(by_record_type.most_common())}")

    if error_count_by_kind:
        print("\nERRORS by kind:")
        for kind, n in error_count_by_kind.most_common():
            print(f"  {kind}: {n}")
        print("\nFirst 20 errors:")
        for e in sample_errors[:20]:
            print(f"  {e}")
        sys.exit(1)
    else:
        print("\nAll records valid.")
        sys.exit(0)


if __name__ == "__main__":
    main()
