#!/usr/bin/env python3
"""Render every page of every PDF to a 200 DPI JPEG (q=88, max 2000 px).

Output: release_1_renders/<stem>/page_NNN.jpg
       release_1_renders/<stem>/_meta.json  (page_count, render params, sha256 of source)

Standalone JPG/PNG records (FBI photos, Apollo VMs) are copied
verbatim as page_001.<native ext>; re-encoding JPG→PNG bloats
photographic scans ~12x for no quality gain.

Memory-safe: ProcessPoolExecutor at PDF granularity, fitz pixmaps are
freed per page, max_dim cap keeps any single pixmap under ~12 MB.
Resumable: skips a PDF whose _meta.json reports the same render
parameters and matching page count on disk.
"""

from __future__ import annotations
import argparse, hashlib, json, os, shutil, sys, time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "release_1_pdfs"
OUT_DIR = ROOT / "release_1_renders"

DPI = 200
MAX_DIM = 2000
JPEG_QUALITY = 88  # DATA_CARD §4 spec: 85-92 for archival scans
RENDER_VERSION = "v1-200dpi-cap2000-jpeg88"


def sha256_file(p: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for blk in iter(lambda: f.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def render_one_pdf(pdf_path_str: str) -> dict:
    pdf_path = Path(pdf_path_str)
    stem = pdf_path.stem
    out = OUT_DIR / stem
    out.mkdir(parents=True, exist_ok=True)
    meta_path = out / "_meta.json"

    src_sha = sha256_file(pdf_path)
    src_size = pdf_path.stat().st_size

    # Resume check
    if meta_path.exists():
        try:
            existing = json.loads(meta_path.read_text())
            if (existing.get("render_version") == RENDER_VERSION
                and existing.get("source_sha256") == src_sha):
                pages_on_disk = sorted(out.glob("page_*.jpg"))
                if len(pages_on_disk) == existing.get("page_count", -1):
                    return {"stem": stem, "skipped": True,
                            "pages": len(pages_on_disk)}
        except Exception:
            pass  # fall through and re-render

    started = time.time()
    doc = fitz.open(pdf_path)
    page_count = len(doc)

    base_zoom = DPI / 72.0
    rendered = 0

    for i, page in enumerate(doc):
        page_num = i + 1
        out_path = out / f"page_{page_num:03d}.jpg"
        tmp_path = out / f".page_{page_num:03d}.tmp.jpg"

        # Compute zoom to keep max dim <= MAX_DIM
        rect = page.rect
        nat_w = rect.width * base_zoom
        nat_h = rect.height * base_zoom
        max_axis = max(nat_w, nat_h)
        zoom = base_zoom * (MAX_DIM / max_axis) if max_axis > MAX_DIM else base_zoom

        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        # JPEG via pix.tobytes (PyMuPDF 1.20+); pix.save() doesn't expose quality
        with open(tmp_path, "wb") as f:
            f.write(pix.tobytes("jpeg", jpg_quality=JPEG_QUALITY))
        os.replace(tmp_path, out_path)
        pix = None  # release immediately
        rendered += 1

    doc.close()

    meta = {
        "stem": stem,
        "kind": "pdf",
        "source_filename": pdf_path.name,
        "source_sha256": src_sha,
        "source_size_bytes": src_size,
        "page_count": page_count,
        "render_dpi": DPI,
        "render_max_dim": MAX_DIM,
        "render_format": "jpeg",
        "render_jpeg_quality": JPEG_QUALITY,
        "render_version": RENDER_VERSION,
        "rendered_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "wall_seconds": round(time.time() - started, 1),
    }
    meta_path.write_text(json.dumps(meta, indent=2))
    return {"stem": stem, "skipped": False, "pages": rendered,
            "wall": meta["wall_seconds"]}


def copy_one_image(img_path_str: str) -> dict:
    """Standalone JPG/PNG records get copied as page_001.<ext> in native
    format. Re-encoding JPG→PNG bloats photographic scans ~12x; pointless."""
    img_path = Path(img_path_str)
    stem = img_path.stem
    out = OUT_DIR / stem
    out.mkdir(parents=True, exist_ok=True)
    meta_path = out / "_meta.json"
    ext = img_path.suffix.lower()
    out_img = out / f"page_001{ext}"

    src_sha = sha256_file(img_path)
    src_size = img_path.stat().st_size

    if meta_path.exists():
        try:
            existing = json.loads(meta_path.read_text())
            if (existing.get("source_sha256") == src_sha and out_img.exists()):
                return {"stem": stem, "skipped": True, "pages": 1}
        except Exception:
            pass

    shutil.copyfile(img_path, out_img)

    meta = {
        "stem": stem,
        "kind": "image",
        "source_filename": img_path.name,
        "source_sha256": src_sha,
        "source_size_bytes": src_size,
        "page_count": 1,
        "page_format": ext.lstrip("."),
        "render_dpi": None,  # native resolution, not rendered
        "render_version": RENDER_VERSION,
        "rendered_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    meta_path.write_text(json.dumps(meta, indent=2))
    return {"stem": stem, "skipped": False, "pages": 1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-j", "--workers", type=int, default=4)
    ap.add_argument("--only", help="comma-separated list of stems to render")
    args = ap.parse_args()

    if not PDF_DIR.exists():
        print(f"ERROR: {PDF_DIR} does not exist", file=sys.stderr)
        sys.exit(1)
    OUT_DIR.mkdir(exist_ok=True)

    pdfs = sorted(p for p in PDF_DIR.iterdir()
                  if p.suffix.lower() == ".pdf" and p.is_file())
    images = sorted(p for p in PDF_DIR.iterdir()
                    if p.suffix.lower() in (".jpg", ".jpeg", ".png")
                    and p.is_file())

    if args.only:
        wanted = set(s.strip() for s in args.only.split(","))
        pdfs = [p for p in pdfs if p.stem in wanted]
        images = [p for p in images if p.stem in wanted]

    print(f"Found {len(pdfs)} PDFs + {len(images)} standalone images "
          f"(workers={args.workers})", flush=True)
    started = time.time()

    done_pdf = skip_pdf = 0
    pages_total = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(render_one_pdf, str(p)): p for p in pdfs}
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                r = fut.result()
            except Exception as e:
                print(f"FAIL {p.name}: {e}", flush=True)
                continue
            pages_total += r["pages"]
            if r["skipped"]:
                skip_pdf += 1
                print(f"  SKIP {r['stem']} ({r['pages']} pages, "
                      f"already rendered)", flush=True)
            else:
                done_pdf += 1
                print(f"  DONE {r['stem']} ({r['pages']} pages, "
                      f"{r['wall']}s)", flush=True)

    # Standalone images are sequential (cheap, no parallelism win)
    done_img = skip_img = 0
    for p in images:
        try:
            r = copy_one_image(str(p))
        except Exception as e:
            print(f"FAIL {p.name}: {e}", flush=True)
            continue
        pages_total += r["pages"]
        if r["skipped"]:
            skip_img += 1
        else:
            done_img += 1

    wall = time.time() - started
    print(f"\nDone in {wall:.1f}s. "
          f"PDF: {done_pdf} rendered, {skip_pdf} skipped. "
          f"IMG: {done_img} copied, {skip_img} skipped. "
          f"Total pages: {pages_total}.", flush=True)


if __name__ == "__main__":
    main()
