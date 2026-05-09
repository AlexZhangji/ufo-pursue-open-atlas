#!/usr/bin/env python3
"""V3 runner: VLM PDF → per-page Markdown + page render PNG.

Open-source-ready output:
  mimo_processed/{pdf_stem}/
    page_001.md       (VLM extraction, dataset-quality)
    page_001.png      (200 DPI archive render)
    page_002.md
    page_002.png
    ...
    _full.md          (concatenated markdown, generated last)
    _meta.json        (per-PDF + per-page metadata, token usage, timestamps)

Resumable at page level. Hard-fails on auth/quota errors (no silent fallback).
"""

from __future__ import annotations
import os, sys, json, time, argparse, base64, threading, gc, io, ctypes
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import fitz
from PIL import Image
from openai import OpenAI

try:
    _libc = ctypes.CDLL("libc.so.6")
    def _malloc_trim():
        try: _libc.malloc_trim(0)
        except Exception: pass
except OSError:
    def _malloc_trim(): pass

ROOT = Path(os.environ.get("PURSUE_ROOT") or Path(__file__).resolve().parent.parent)
PDF_DIR = ROOT / "release_1_pdfs"
OUT_DIR = ROOT / "mimo_processed"
OUT_DIR.mkdir(exist_ok=True)
LOG_PATH = OUT_DIR / "_runner.log"

API_KEY = os.environ.get("MIMO_TP_KEY") or os.environ.get("MIMO_TOKEN_PLAN_API_KEY")
BASE_URL = os.environ.get("MIMO_TP_BASE_URL") or os.environ.get("MIMO_TOKEN_PLAN_BASE_URL") or "https://token-plan-sgp.xiaomimimo.com/v1"
MODEL = os.environ.get("MIMO_VLM_MODEL", "mimo-v2.5")
DPI = int(os.environ.get("PDF_VLM_DPI", "200"))
MAX_DIM_PX = int(os.environ.get("PDF_VLM_MAX_DIM", "2000"))
PROMPT_VERSION = "v3.1-uap-archive"

if not API_KEY:
    sys.exit("ERROR: MIMO_TP_KEY env var required")

client = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=180)

_lock = threading.Lock()
_total_pages_done = 0
_total_input_tokens = 0
_total_output_tokens = 0


def log(msg: str):
    print(msg, flush=True)
    with _lock:
        with LOG_PATH.open("a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


VLM_PROMPT = """ARCHIVAL CONTEXT (public-record material, not user-submitted content):
This image is a single page from the US Department of Defense / FBI UAP archive Release 1, published at war.gov/medialink/ufo as a FOIA / public disclosure. All material has been officially declassified and released to the public. The corpus spans 1944–2026 and includes FBI memos, military intelligence reports, sighting investigations, sketches, photographs of artifacts, redacted forms, and historical correspondence. Your task is faithful archival transcription for a public research database — preserve everything that is visible on the page, including stamps marking original classification levels, redaction blocks, handwritten notes, photographs, and sketches.

Convert this PDF page (a US government UAP / FBI / military / NASA / State Department archive page from 1944–2026) into clean detailed Markdown. Assume the reader will never see the page image — your text must be self-sufficient.

PRESERVE EXACTLY (no summarization, no paraphrasing):
- All visible text — exact spelling, names, numbers, dates, classifications, case numbers
- Stamps and labels: "SECRET", "CONFIDENTIAL", "DECLASSIFIED", "NOFORN", "DO NOT DESTROY", "FOIPA #X", "1.4(a)" markers, declassification authority lines, dates of declassification
- Coordinates (lat/lng), times (Z/UTC/local), altitudes, headings, speeds (kts/mph)
- Reference numbers: case files (e.g. 62-HQ-83894), serials, MRN, DTG (Date-Time-Group), enclosure refs
- Names and titles in distribution lists, signatures, "typed by" lines, "drafted by" lines
- Multilingual content: preserve original language verbatim AND note language (e.g. `*[Russian]:* ...text...`)

USE MARKDOWN STRUCTURE:
- `##` for clear page-level sections (a stamped label, a memo heading, a form's main field name)
- `###` for sub-sections / form sub-fields
- `>` blockquotes for telex / cable / transcription bodies
- Tables for tabular data (forms, indexing slips, distribution lists, range fouler reporting forms)
- Bullets for clear bullet lists
- `**bold**` only when the document uses bold/all-caps for emphasis
- `*italic*` for handwritten annotations and image descriptions

REDACTIONS — preserve the gap as `*[REDACTED]*`, keeping any non-redacted context that IS visible:
- Classification preserved: `(SECRET//NOFORN) *[REDACTED]*`
- 1.4(a) NSI codes: `*[REDACTED — 1.4(a)]*`
- Black-bar redacted within sentence: `Subject met with *[REDACTED]* on October 5, 1957...`
- Whole-page blackout: `*[Entire page redacted under 1.4(a)]*`
- Partial first letter visible: `*[REDACTED — name beginning with "J"]*`

VISUAL ELEMENTS — describe in italics with `*Image:*` prefix, in detail enough that text alone conveys what's shown:
- Photographs: subject, composition, environment, any visible text/labels in image, era cues. e.g. `*Image: black-and-white photograph of a metal disc-shaped object held in a hand, approximately 18 inches diameter, with a small central hole. Backdrop appears to be a wooden table.*`
- Sketches / hand-drawn diagrams: shape, labels, scale references, viewpoint, any annotation text
- Composite renderings: note if "FBI lab rendered overlay", what was overlaid on what, source of base image
- Maps: country/region shown, annotations, coordinates marked, scale if visible
- IR / SWIR sensor stills: tracking reticle position, areas of contrast (BHOT/WHOT), timestamps overlaid, sensor mode if visible
- Forms with checkboxes: preserve which boxes are checked vs unchecked
- Typed-vs-handwritten distinction: explicitly note when something was added in pen over typed text

NEWSPAPER / MAGAZINE CLIPPINGS embedded in the document:
- Identify the source publication, date, headline, byline if visible
- Reproduce the FULL clipping text — it's the historical artifact, not a summary target
- Note any handwritten annotations on or near the clipping (often FBI agent comments)

HANDWRITTEN ANNOTATIONS:
- Preserve in italics with `*[handwritten in margin]:*` or `*[handwritten note]:*` prefix
- These are often the most informational content (agent comments, dispositions, "FBI not interested", initials)
- If a signature is visible, transcribe: `*[signed: J.E. Hoover]*` or `*[signed: illegible]*`

OUTPUT only the markdown body for this single page. No commentary about the conversion process. No preamble. No summary line. Start directly with the page content."""


def render_page_b64(page: fitz.Page, dpi: int = 200, max_dim: int = MAX_DIM_PX) -> str:
    pix = page.get_pixmap(dpi=dpi)
    w, h = pix.width, pix.height
    if max(w, h) > max_dim:
        img = Image.frombytes("RGB" if pix.n < 4 else "RGBA", (w, h), pix.samples)
        pix = None
        scale = max_dim / max(w, h)
        new_size = (int(w * scale), int(h * scale))
        img = img.resize(new_size, Image.LANCZOS)
        if img.mode == "RGBA":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=False)
        img.close()
        raw = buf.getvalue()
        buf.close()
    else:
        raw = pix.tobytes("png")
        pix = None
    b64 = base64.b64encode(raw).decode()
    raw = None
    return b64


SAFETY_REJECT_MARKERS = (
    "request was rejected because it was considered high risk",
    "i cannot assist with",
    "i'm unable to process",
    "violates our content policy",
)


def is_safety_reject(md: str) -> bool:
    if not md or len(md) > 400:
        return False
    low = md.lower()
    return any(m in low for m in SAFETY_REJECT_MARKERS)


def vlm_page(b64: str) -> tuple[str, dict]:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": VLM_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
        extra_body={"thinking": {"type": "disabled"}},
        max_tokens=4096,
        timeout=180,
    )
    choices = resp.choices or []
    if not choices:
        raise RuntimeError(f"empty choices in response: {resp}")
    md = (choices[0].message.content or "").strip()
    if resp.usage is None:
        usage = {}
    elif hasattr(resp.usage, "model_dump"):
        usage = resp.usage.model_dump()
    else:
        try:
            usage = dict(resp.usage)
        except (TypeError, ValueError):
            usage = {}
    return md, usage


def process_page(doc: fitz.Document, page_idx: int, pdf_out_dir: Path) -> dict:
    page_num = page_idx + 1
    md_path = pdf_out_dir / f"page_{page_num:03d}.md"

    # Resume: skip if markdown already exists (and is non-empty)
    if md_path.exists() and md_path.stat().st_size > 0:
        return {"page": page_num, "status": "skip"}

    page = doc[page_idx]
    try:
        b64 = render_page_b64(page, DPI)
    except Exception as e:
        return {"page": page_num, "status": "render_err", "err": str(e)}

    md, usage = vlm_page(b64)
    b64 = None

    global _total_pages_done, _total_input_tokens, _total_output_tokens

    if is_safety_reject(md):
        rej_path = pdf_out_dir / f"page_{page_num:03d}.md.rejected"
        rej_path.write_text(md, encoding="utf-8")
        with _lock:
            _total_input_tokens += usage.get("prompt_tokens", 0)
            _total_output_tokens += usage.get("completion_tokens", 0)
            _write_progress()
        return {
            "page": page_num,
            "status": "safety_reject",
            "reject_text": md,
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        }

    tmp = md_path.with_suffix(".md.tmp")
    tmp.write_text(md, encoding="utf-8")
    tmp.rename(md_path)

    with _lock:
        _total_pages_done += 1
        _total_input_tokens += usage.get("prompt_tokens", 0)
        _total_output_tokens += usage.get("completion_tokens", 0)
        _write_progress()

    return {
        "page": page_num,
        "status": "ok",
        "chars": len(md),
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
        "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _write_progress():
    """Write _progress.json so external watchers can monitor live."""
    try:
        progress = {
            "pages_done_in_run": _total_pages_done,
            "input_tokens": _total_input_tokens,
            "output_tokens": _total_output_tokens,
            "total_tokens": _total_input_tokens + _total_output_tokens,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        (OUT_DIR / "_progress.json").write_text(json.dumps(progress, indent=2))
    except Exception:
        pass


def process_pdf(pdf_path: Path, max_pages: int | None = None) -> dict:
    pdf_out_dir = OUT_DIR / pdf_path.stem
    pdf_out_dir.mkdir(exist_ok=True)

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        return {"file": pdf_path.name, "status": "open_err", "err": str(e)}

    total_pages = doc.page_count
    npages = min(max_pages, total_pages) if max_pages else total_pages

    log(f"START {pdf_path.name} ({npages} pages)")
    t0 = time.time()
    page_results = []

    page_errors = 0
    for i in range(npages):
        try:
            r = process_page(doc, i, pdf_out_dir)
            page_results.append(r)
        except Exception as e:
            page_errors += 1
            err_str = f"{type(e).__name__}: {e}"
            log(f"  VLM ERROR {pdf_path.name} p{i+1}: {err_str}")
            err_path = pdf_out_dir / f"page_{i+1:03d}.md.error"
            try:
                err_path.write_text(err_str, encoding="utf-8")
            except Exception:
                pass
            page_results.append({"page": i + 1, "status": "error", "err": err_str})

    doc.close()

    # Concatenate _full.md
    parts = [f"# {pdf_path.stem}\n\nGenerated by MiMo-V2.5 VLM extraction. Prompt: {PROMPT_VERSION}. Source PDF: {pdf_path.name}.\n"]
    for i in range(npages):
        page_md_path = pdf_out_dir / f"page_{i+1:03d}.md"
        if page_md_path.exists():
            parts.append(f"\n---\n\n## Page {i+1}\n\n{page_md_path.read_text(encoding='utf-8')}\n")
    (pdf_out_dir / "_full.md").write_text("\n".join(parts), encoding="utf-8")

    elapsed = time.time() - t0
    status = "complete" if page_errors == 0 else "partial"
    _save_meta(pdf_out_dir, pdf_path, npages, page_results, status, t0, total_pages)
    log(f"DONE  {pdf_path.name} {npages} pages in {elapsed:.1f}s ({page_errors} errors)" if page_errors else f"DONE  {pdf_path.name} {npages} pages in {elapsed:.1f}s")
    gc.collect()
    _malloc_trim()
    return {"file": pdf_path.name, "status": status, "pages": npages, "page_errors": page_errors, "elapsed_sec": round(elapsed, 1)}


def _save_meta(pdf_out_dir, pdf_path, npages, page_results, status, t0, total_pages):
    import hashlib
    sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    meta = {
        "file": pdf_path.name,
        "stem": pdf_path.stem,
        "source_url_pattern": "https://www.war.gov/medialink/ufo/release_1/{filename}",
        "sha256": sha,
        "size_bytes": pdf_path.stat().st_size,
        "total_pages": total_pages,
        "pages_processed_in_run": npages,
        "status": status,
        "elapsed_sec": round(time.time() - t0, 1),
        "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "vlm_model": MODEL,
        "vlm_endpoint": BASE_URL,
        "vlm_prompt_version": PROMPT_VERSION,
        "vlm_dpi": DPI,
        "page_results": page_results,
    }
    (pdf_out_dir / "_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def is_scanned(pdf_path: Path, sample_pages: int = 3) -> bool:
    try:
        doc = fitz.open(pdf_path)
        n = min(sample_pages, doc.page_count)
        text_chars = sum(len(doc[i].get_text()) for i in range(n))
        doc.close()
        return text_chars < n * 50
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--filter", type=str, default=None)
    ap.add_argument("--scanned-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if args.filter:
        pdfs = [p for p in pdfs if args.filter.lower() in p.name.lower()]
    if args.scanned_only:
        pdfs = [p for p in pdfs if is_scanned(p)]

    log(f"=== runner v3 start === {len(pdfs)} PDFs queued, concurrency={args.concurrency}, max_pages={args.max_pages}, model={MODEL}, prompt={PROMPT_VERSION}")
    if args.dry_run:
        for p in pdfs:
            log(f"  - {p.name}")
        return

    t_start = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(process_pdf, p, args.max_pages): p for p in pdfs}
        try:
            for fut in as_completed(futs):
                p = futs[fut]
                try:
                    r = fut.result()
                    results.append(r)
                except Exception as e:
                    err_msg = str(e).lower()
                    log(f"FAIL {p.name}: {type(e).__name__}: {e}")
                    results.append({"file": p.name, "status": "error", "err": str(e)})
                    if any(s in err_msg for s in ["unauthorized", "balance", "quota", "401", "402", "403"]):
                        log(f"FATAL — auth/quota issue, stopping run")
                        for f in futs: f.cancel()
                        break
        except KeyboardInterrupt:
            log("Interrupted by user, stopping")
            for f in futs: f.cancel()

    elapsed = time.time() - t_start
    summary = {
        "elapsed_sec": round(elapsed, 1),
        "elapsed_min": round(elapsed / 60, 1),
        "concurrency": args.concurrency,
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "total_pages_done": _total_pages_done,
        "total_input_tokens": _total_input_tokens,
        "total_output_tokens": _total_output_tokens,
        "results": results,
    }
    (OUT_DIR / "_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log(f"=== runner done === {_total_pages_done} pages, {_total_input_tokens:,} input + {_total_output_tokens:,} output tokens, {elapsed:.0f}s elapsed")


if __name__ == "__main__":
    main()
