#!/usr/bin/env python3
"""Re-run mimo on each page with image content, classify + re-describe, judge consistency.
Pages with low judge score OR photograph/sketch category get queued for GPT fallback.

Output:
  image_audit/recheck/<stem>/<page>.json — per-page recheck record
  image_audit/recheck/_summary.json — aggregate decisions
  image_audit/recheck/_fallback_queue.json — list to send to GPT next
"""

from __future__ import annotations
import os, re, json, io, base64, time, threading, argparse, gc
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import fitz
from PIL import Image
from openai import OpenAI

ROOT = Path(os.environ.get("PURSUE_ROOT") or Path(__file__).resolve().parent.parent)
PROCESSED = ROOT / "mimo_processed"
PDFS = ROOT / "release_1_pdfs"
OUT_DIR = ROOT / "image_audit" / "recheck"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MIMO_KEY = os.environ.get("MIMO_TP_KEY") or os.environ.get("MIMO_TOKEN_PLAN_API_KEY")
MIMO_BASE = "https://token-plan-sgp.xiaomimimo.com/v1"
MIMO_MODEL = "mimo-v2.5"

mimo = OpenAI(base_url=MIMO_BASE, api_key=MIMO_KEY, timeout=180)

IMG_RE = re.compile(r'\*Image:\s*(.+?)\*', re.DOTALL)

CATEGORIES = ["photograph", "sketch", "diagram", "map", "chart_or_graph",
              "form_scan", "newspaper_clipping", "stamp_or_label_only",
              "blank_or_back_of_page", "handwritten_only", "redacted_only", "other"]

EXTRACT_PROMPT = """You are auditing images embedded inside a US government UAP / FBI / military / NASA / State Department PDF page (war.gov public-record release, 1944-2026, fully declassified). We are checking how accurate previous image-tag descriptions are.

Your task: identify every distinct VISUAL element on this page and describe it factually. By visual element we mean: photographs, hand-drawn sketches, diagrams, maps, charts, graphs, illustrations, newspaper-clipping illustrations, and any other graphical content embedded in the page. Typed body text and form structure are NOT visual elements; ignore them. Stamps and handwritten annotations are also not the focus, but you may note them if they are the only visible content.

Output JSON only (no prose, no markdown fences):
{
  "elements": [
    {
      "category": "<one of: photograph | sketch | diagram | map | chart_or_graph | newspaper_clipping_illustration | stamp_or_label_only | blank_or_back_of_page | redacted_only | typed_text_only | other>",
      "description": "<concise factual description: count of objects, what is depicted, captions or labels visible inside or below the image, and any text/numbers visible inside the visual element itself. If the image is faint or illegible, say so rather than guessing.>"
    }
  ]
}

Strict rules:
- Count objects in photographs precisely. If you see one mummified figure, say "one"; do not guess "two" or "three".
- Do not invent specific names, dates, file numbers, or quoted text. Only report text that is clearly legible inside or directly captioning the visual element.
- For pages with no actual photograph, sketch, diagram, map, or chart (e.g. plain typed memos, blank backs, pure stamp-only pages), return a single element with the appropriate category (typed_text_only / blank_or_back_of_page / stamp_or_label_only / redacted_only) and a short description.
- Output JSON only. No surrounding text."""


JUDGE_PROMPT = """You are comparing two independent descriptions (A and B) of the IMAGES on the same archival PDF page. Both descriptions were produced by VLM systems and may contain hallucination. Your job is to score factual consistency on the VISUAL content only.

Wording, sentence structure, and writing style do not matter at all. Whether one side is shorter or longer does not matter. ONLY the substance about what is depicted matters.

Ignore disagreements about typed body text, form fields, or document structure that surrounds the images. Only compare claims about actual visual content (photographs, sketches, diagrams, maps, charts, illustrations) and the specific text inside or directly captioning those images.

Description A (original):
{a}

Description B (re-run):
{b}

Score 1-3:
- 3 = factually consistent on images. Same number of visual elements, same categories (photograph / sketch / etc), same object counts inside photographs, same captions/labels where quoted. Wording can differ entirely. Specific quoted text matches when both sides quote it.
- 2 = mostly consistent on images. Both sides agree on the main visual content and categories. One side adds detail the other omits (caption text, date, file number) but the two sides do NOT contradict each other on any specific quoted text.
- 1 = factually inconsistent on images. At least one of: (a) different object counts (1 figure vs 3 figures); (b) different categories (photograph vs sketch); (c) one side quotes specific verbatim text inside an image (e.g. names, file numbers, captions, stamp text) that the other side reads completely differently or says is illegible; (d) the two descriptions are clearly about different visual content.

CRITICAL: if both sides claim to quote the SAME stamp or text but give DIFFERENT specific verbatim strings (e.g. one reads "ACCD-CCCP Y IURS" and the other reads "RECD-HC-REF A HOURS"), that is a contradiction on verbatim text — score 1, hallucination_suspected = true. At least one side is fabricating from low-confidence pixels.

Hallucination flag: set hallucination_suspected = true when ANY of the following:
- One side states specific names, dates, file numbers, or quoted text inside images that the other side does not see at all
- Both sides quote what should be the same text but give substantially different verbatim strings
- One side describes specific objects (e.g. "three figures") and the other describes a different count
- One side reads structured content (e.g. "list of names: Mr. Tolson, Mr. Van...") that the other side calls illegible or absent

Hallucination is the most concerning failure mode — be willing to flag it.

Special case: if both sides agree there is NO real visual content on the page (e.g. both say it is just a typed memo, or just a blank back of page), score = 3 and hallucination_suspected = false. The page has no images to disagree about.

Output JSON only, no prose, no markdown fences:
{{"score": <1|2|3>, "reason": "<one sentence pointing to the specific factual basis on visual content>", "hallucination_suspected": <true|false>, "fallback_recommended": <true if score is 1, or hallucination_suspected is true, else false>}}"""


def render_b64(pdf_path: Path, page_idx: int, dpi: int = 200, max_dim: int = 1500) -> str:
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=dpi)
        w, h = pix.width, pix.height
        samples = pix.samples
        n = pix.n
        pix = None
        img = Image.frombytes("RGB" if n < 4 else "RGBA", (w, h), samples)
        samples = None
        if img.mode == "RGBA":
            img = img.convert("RGB")
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        img.close()
        img = None
        data = buf.getvalue()
        buf.close()
        return base64.b64encode(data).decode()
    finally:
        doc.close()


def call_mimo_extract(b64: str) -> dict:
    resp = mimo.chat.completions.create(
        model=MIMO_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": EXTRACT_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]}],
        extra_body={"thinking": {"type": "disabled"}},
        max_tokens=2000,
        response_format={"type": "json_object"},
    )
    content = ((resp.choices or [None])[0].message.content or "").strip() if resp.choices else "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # try to extract JSON substring
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return {"elements": [], "_parse_error": content[:300]}


def call_mimo_judge(desc_a: str, desc_b: str) -> dict:
    prompt = JUDGE_PROMPT.format(a=desc_a, b=desc_b)
    resp = mimo.chat.completions.create(
        model=MIMO_MODEL,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"thinking": {"type": "disabled"}},
        max_tokens=300,
        response_format={"type": "json_object"},
    )
    content = ((resp.choices or [None])[0].message.content or "").strip() if resp.choices else "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return {"score": 0, "reason": "parse_error", "fallback_recommended": True}


def collect_target_pages():
    """Pages with at least one *Image:* tag."""
    targets = []
    for pdf_dir in sorted(PROCESSED.iterdir()):
        if not pdf_dir.is_dir():
            continue
        pdf_path = PDFS / f"{pdf_dir.name}.pdf"
        if not pdf_path.exists():
            continue
        for md in sorted(pdf_dir.glob("page_*.md")):
            text = md.read_text(encoding='utf-8', errors='replace')
            tags = [m.group(1).strip() for m in IMG_RE.finditer(text)]
            if not tags:
                continue
            page_num = int(md.name.split("_")[1].split(".")[0])
            targets.append({
                "pdf_stem": pdf_dir.name,
                "page_num": page_num,
                "pdf_path": str(pdf_path),
                "md_path": str(md),
                "original_image_tags": tags,
            })
    return targets


def process_one(target: dict, force: bool = False) -> dict:
    out_path = OUT_DIR / target["pdf_stem"] / f"page_{target['page_num']:03d}.json"
    if out_path.exists() and not force:
        try:
            return {"skip": True, **json.loads(out_path.read_text())}
        except Exception:
            pass
    out_path.parent.mkdir(exist_ok=True)

    try:
        b64 = render_b64(Path(target["pdf_path"]), target["page_num"] - 1)
    except Exception as e:
        rec = {"status": "render_err", "err": str(e), "target": target}
        out_path.write_text(json.dumps(rec, ensure_ascii=False))
        return rec

    try:
        extract = call_mimo_extract(b64)
    except Exception as e:
        rec = {"status": "mimo_extract_err", "err": str(e)[:300], "target": target}
        out_path.write_text(json.dumps(rec, ensure_ascii=False))
        return rec

    new_desc_concat = "\n".join(
        f"[{el.get('category','?')}] {el.get('description','')}"
        for el in extract.get("elements", [])
    )
    orig_desc_concat = "\n".join(target["original_image_tags"])

    if not new_desc_concat.strip():
        judge = {"score": 0, "reason": "extract empty"}
    else:
        try:
            judge = call_mimo_judge(orig_desc_concat, new_desc_concat)
        except Exception as e:
            judge = {"score": 0, "reason": f"judge_err: {str(e)[:200]}"}

    categories = [el.get("category", "other") for el in extract.get("elements", [])]
    has_visual = any(c in ("photograph", "sketch", "diagram", "map", "chart_or_graph", "newspaper_clipping_illustration") for c in categories)
    score = judge.get("score", 0)
    halluc = judge.get("hallucination_suspected", False)
    fallback = (
        score == 0  # parse / extract failure
        or score == 1
        or judge.get("fallback_recommended", False)
        or (score == 2 and halluc)
        or (score == 2 and has_visual)
    )

    rec = {
        "pdf_stem": target["pdf_stem"],
        "page_num": target["page_num"],
        "original_image_tags": target["original_image_tags"],
        "rerun_extract": extract,
        "judge": judge,
        "categories": categories,
        "has_visual": has_visual,
        "fallback_to_gpt": fallback,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    out_path.write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--filter-stem", type=str, default=None)
    args = ap.parse_args()

    targets = collect_target_pages()
    if args.filter_stem:
        targets = [t for t in targets if args.filter_stem in t["pdf_stem"]]
    if args.limit:
        targets = targets[:args.limit]
    print(f"Targets: {len(targets)} pages with image tags", flush=True)

    score_counts = {0: 0, 1: 0, 2: 0, 3: 0}
    fallback_count = 0
    cat_counts = {}
    error_count = 0

    lock = threading.Lock()
    done_count = 0

    def progress(rec):
        nonlocal done_count, fallback_count, error_count
        with lock:
            done_count += 1
            s = (rec.get("judge") or {}).get("score", 0)
            score_counts[s] = score_counts.get(s, 0) + 1
            if rec.get("fallback_to_gpt"):
                fallback_count += 1
            if rec.get("status") in ("render_err", "mimo_extract_err"):
                error_count += 1
            for c in rec.get("categories", []):
                cat_counts[c] = cat_counts.get(c, 0) + 1
            if done_count % 25 == 0 or done_count == len(targets):
                print(f"  {done_count}/{len(targets)} | s3={score_counts.get(3,0)} s2={score_counts.get(2,0)} s1={score_counts.get(1,0)} s0={score_counts.get(0,0)} | fallback={fallback_count} | err={error_count}", flush=True)

    target_iter = iter(targets)
    in_flight = {}
    window = max(args.concurrency + 2, 6)

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        for _ in range(window):
            try:
                t = next(target_iter)
            except StopIteration:
                break
            in_flight[ex.submit(process_one, t, args.force)] = True

        while in_flight:
            done, _pending = wait(list(in_flight.keys()), return_when=FIRST_COMPLETED)
            for fut in done:
                in_flight.pop(fut, None)
                try:
                    rec = fut.result()
                    progress(rec)
                    rec = None
                except Exception as e:
                    print(f"thread error: {e}", flush=True)
                    error_count += 1
                try:
                    t = next(target_iter)
                    in_flight[ex.submit(process_one, t, args.force)] = True
                except StopIteration:
                    pass
            gc.collect()

    summary = {
        "total": len(targets),
        "score_counts": score_counts,
        "fallback_count": fallback_count,
        "error_count": error_count,
        "category_counts": cat_counts,
        "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (OUT_DIR / "_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    fallback_queue = []
    for stem_dir in sorted(OUT_DIR.iterdir()):
        if not stem_dir.is_dir():
            continue
        for jp in sorted(stem_dir.glob("page_*.json")):
            try:
                r = json.loads(jp.read_text())
            except Exception:
                continue
            if r.get("fallback_to_gpt"):
                fallback_queue.append({
                    "pdf_stem": r.get("pdf_stem"),
                    "page_num": r.get("page_num"),
                    "categories": r.get("categories", []),
                    "judge_score": (r.get("judge") or {}).get("score", 0),
                    "judge_reason": (r.get("judge") or {}).get("reason", ""),
                })
    (OUT_DIR / "_fallback_queue.json").write_text(json.dumps(fallback_queue, indent=2, ensure_ascii=False))
    print(f"\nSummary: {json.dumps(summary, indent=2)}")
    print(f"Fallback queue: {len(fallback_queue)} pages")


if __name__ == "__main__":
    main()
