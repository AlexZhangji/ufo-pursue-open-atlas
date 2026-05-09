#!/usr/bin/env python3
"""Build pages-XXXXX-of-XXXXX.parquet shards from corpus.jsonl + page renders.

Each row carries the same fields as corpus.jsonl plus an `image` column
typed as datasets.Image(), so `load_dataset(...)` returns PIL.Image
objects directly with no manual cast_column step.

Output:
  pages-00000-of-00005.parquet
  pages-00001-of-00005.parquet
  ...

Sharded so each parquet stays around 400 MB — friendly to HF LFS,
parallel-loadable, and well within HF's per-file recommendations.

Run from repo root:
    python scripts/build_parquet_shards.py
"""

from __future__ import annotations
import argparse, json
from pathlib import Path

from datasets import Dataset, Features, Image, Sequence, Value

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus.jsonl"
NUM_SHARDS_DEFAULT = 5
PAGES_DIR = "pages"
TEXT_DIR = "text"
PAGES_NAME = "train-{idx:05d}-of-{total:05d}.parquet"
TEXT_NAME = "train.parquet"


# Static feature schema — has to match the field set + types we actually
# emit for the `pages` parquet config. corpus.jsonl-side fields are kept
# in sync 1:1 except `page_image_path` / `page_image_format` are dropped
# (replaced by the inline `image` column).
# `image` first so HF dataset viewer shows it as leftmost column.
# All other fields follow corpus.jsonl ordering 1:1.
FEATURES = Features({
    "image":                           Image(),
    "record_id":                       Value("string"),
    "pdf_stem":                        Value("string"),
    "page_num":                        Value("int32"),
    "total_pages":                     Value("int32"),
    "title":                           Value("string"),
    "agency":                          Value("string"),
    "record_type":                     Value("string"),
    "year":                            Value("int32"),
    "incident_date_iso":               Value("string"),
    "incident_location":               Value("string"),
    "text":                            Value("string"),
    "text_chars":                      Value("int32"),
    "image_tags":                      Sequence(Value("string")),
    "image_tag_source":                Value("string"),
    "image_tag_audit_score":           Value("int32"),
    "image_tag_audit_categories":      Sequence(Value("string")),
    "source_url":                      Value("string"),
    "sha256":                          Value("string"),
    "file_size_bytes":                 Value("int64"),
    "incident_location_corrected":     Value("bool"),
    "year_inferred":                   Value("bool"),
    "incident_date_corrected":         Value("bool"),
    "description_blurb":               Value("string"),
    "dvids_video_id":                  Value("string"),
    "vlm_model":                       Value("string"),
    "vlm_prompt_version":              Value("string"),
    "vlm_dpi":                         Value("int32"),
    "extraction_completed_at":         Value("string"),
    "render_dpi":                      Value("int32"),
    "render_max_dim":                  Value("int32"),
    "render_jpeg_quality":             Value("int32"),
    "render_version":                  Value("string"),
})

# Text-only schema for the lightweight `text` config (drop image bytes
# but keep page_image_path for users who clone the repo + have local renders).
TEXT_FEATURES = Features({
    f: t for f, t in FEATURES.items() if f != "image"
})
TEXT_FEATURES = Features({
    **{k: v for k, v in TEXT_FEATURES.items()},
    "page_image_path":   Value("string"),
    "page_image_format": Value("string"),
})


def to_pages_row(rec: dict) -> dict:
    """Transform a corpus.jsonl record into a pages-config parquet row
    (image bytes embedded, image as first column for viewer ordering)."""
    img_rel = rec.get("page_image_path")
    if not img_rel:
        return None
    img_path = ROOT / img_rel
    if not img_path.exists():
        return None
    out = {k: rec.get(k) for k in FEATURES.keys() if k != "image"}
    out["image"] = {"bytes": img_path.read_bytes(), "path": None}
    return out


def to_text_row(rec: dict) -> dict:
    """Text-only row — keeps page_image_path string for users who want
    to resolve images themselves, drops the inline image bytes column."""
    return {k: rec.get(k) for k in TEXT_FEATURES.keys()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--num-shards", type=int, default=NUM_SHARDS_DEFAULT)
    args = ap.parse_args()

    pages_rows, text_rows, skipped_pages = [], [], 0
    with CORPUS.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            text_rows.append(to_text_row(rec))
            page_row = to_pages_row(rec)
            if page_row is None:
                skipped_pages += 1
            else:
                pages_rows.append(page_row)

    print(f"corpus.jsonl rows: {len(text_rows)}")
    print(f"  pages config (with rendered image): {len(pages_rows)}")
    print(f"  pages skipped (no render): {skipped_pages}")

    # ---- text config: single parquet, no image bytes ----
    text_dir = ROOT / TEXT_DIR
    text_dir.mkdir(exist_ok=True)
    text_ds = Dataset.from_list(text_rows, features=TEXT_FEATURES)
    text_out = text_dir / TEXT_NAME
    text_ds.to_parquet(text_out.as_posix())
    print(f"\nwrote {TEXT_DIR}/{TEXT_NAME}: "
          f"{text_ds.num_rows} rows, "
          f"{text_out.stat().st_size/1024/1024:.1f} MB")

    # ---- pages config: sharded parquet with image bytes inline ----
    pages_dir = ROOT / PAGES_DIR
    pages_dir.mkdir(exist_ok=True)
    pages_ds = Dataset.from_list(pages_rows, features=FEATURES)
    n = args.num_shards
    for i in range(n):
        shard = pages_ds.shard(num_shards=n, index=i, contiguous=True)
        out = pages_dir / PAGES_NAME.format(idx=i, total=n)
        shard.to_parquet(out.as_posix())
        size_mb = out.stat().st_size / 1024 / 1024
        print(f"  wrote {PAGES_DIR}/{out.name}: {shard.num_rows} rows, {size_mb:.1f} MB")

    total_mb = sum(
        (pages_dir / PAGES_NAME.format(idx=i, total=n)).stat().st_size
        for i in range(n)
    ) / 1024 / 1024
    print(f"\nTotal pages parquet: {total_mb:.1f} MB across {n} shards")


if __name__ == "__main__":
    main()
