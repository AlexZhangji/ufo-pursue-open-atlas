#!/usr/bin/env python3
"""Generate web/thumbs/<stem>/page_NNN.jpg from release_1_renders/.

400px wide JPEG q75 — fits in <40KB per page, ~130MB total for the v0.1
release. Designed to ship as static assets next to web/search.html so the
hybrid search UI can show inline previews without ever loading the 200dpi
originals.

Reads corpus.jsonl to drive the work — only renders that appear in the
corpus get a thumbnail, so the output is exactly in sync with what the
search index will reference.

Run from repo root:
    python scripts/build_thumbnails.py
    python scripts/build_thumbnails.py --source ../pursue-open-atlas/release_1_renders --width 400
"""

from __future__ import annotations
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus.jsonl"
DEFAULT_SOURCE = ROOT.parent / "pursue-open-atlas" / "release_1_renders"
DEFAULT_OUT = ROOT / "web" / "thumbs"


def resize_one(src: Path, dst: Path, width: int, quality: int, force: bool) -> tuple[str, int]:
    """Resize one image. Returns (status, bytes_written).
    status ∈ {written, skipped_exists, skipped_missing_src, error}."""
    if not src.exists():
        return ("skipped_missing_src", 0)
    if dst.exists() and not force:
        return ("skipped_exists", dst.stat().st_size)
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")  # JPEG can't carry alpha
            w, h = im.size
            if w > width:
                new_h = int(h * (width / w))
                im = im.resize((width, new_h), Image.LANCZOS)
            im.save(dst, "JPEG", quality=quality, optimize=True, progressive=True)
        return ("written", dst.stat().st_size)
    except Exception as e:
        print(f"  error on {src}: {e}", file=sys.stderr)
        return ("error", 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                    help="release_1_renders root (default: ../pursue-open-atlas/release_1_renders)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="output dir (default: web/thumbs)")
    ap.add_argument("--width", type=int, default=400)
    ap.add_argument("--quality", type=int, default=75)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--force", action="store_true", help="overwrite existing thumbs")
    args = ap.parse_args()

    if not args.source.exists():
        print(f"source dir does not exist: {args.source}", file=sys.stderr)
        sys.exit(1)

    jobs: list[tuple[Path, Path]] = []
    with CORPUS.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            rel = rec.get("page_image_path")
            if not rel:
                continue
            # rel looks like 'release_1_renders/<stem>/page_NNN.jpg'.
            # We strip the leading 'release_1_renders/' so we can re-root it
            # under any source dir the user points at.
            rel_path = Path(rel)
            if rel_path.parts and rel_path.parts[0] == "release_1_renders":
                rel_path = Path(*rel_path.parts[1:])
            src = args.source / rel_path
            # Thumb keeps the same relative path under out/.
            # Force .jpg extension since all thumbs are JPEG, regardless of
            # source format (some standalone records are .png).
            dst = args.out / rel_path.with_suffix(".jpg")
            jobs.append((src, dst))

    print(f"queued {len(jobs)} thumbnails")
    print(f"  source: {args.source}")
    print(f"  out:    {args.out}")
    print(f"  width:  {args.width}px, quality {args.quality}, workers {args.workers}")

    counts = {"written": 0, "skipped_exists": 0, "skipped_missing_src": 0, "error": 0}
    bytes_total = 0
    done = 0

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [
            ex.submit(resize_one, src, dst, args.width, args.quality, args.force)
            for src, dst in jobs
        ]
        for fut in as_completed(futs):
            status, sz = fut.result()
            counts[status] += 1
            bytes_total += sz
            done += 1
            if done % 200 == 0 or done == len(jobs):
                print(f"  [{done}/{len(jobs)}] "
                      f"written={counts['written']} "
                      f"skip_exists={counts['skipped_exists']} "
                      f"missing_src={counts['skipped_missing_src']} "
                      f"err={counts['error']}")

    print(f"\ndone — {bytes_total/1024/1024:.1f} MB across {counts['written']+counts['skipped_exists']} thumbnails")
    if counts["skipped_missing_src"]:
        print(f"  warn: {counts['skipped_missing_src']} source renders missing")
    if counts["error"]:
        print(f"  warn: {counts['error']} errors — see stderr")


if __name__ == "__main__":
    main()
