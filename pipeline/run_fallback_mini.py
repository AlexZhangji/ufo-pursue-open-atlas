#!/usr/bin/env python3
"""Run gpt-5.4-mini on the RELAXED fallback queue (has_visual + s0/s1/s2).
Reads recheck/ records, sends pages with at least one true visual category
to gpt-5.4-mini, stores per-page result.

Output:
  image_audit/fallback_mini/<stem>/page_NNN.json
  image_audit/fallback_mini/_summary.json
"""

from __future__ import annotations
import os, re, json, io, base64, time, threading, argparse, gc
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import fitz
from PIL import Image
from openai import OpenAI

ROOT = Path(os.environ.get("PURSUE_ROOT") or Path(__file__).resolve().parent.parent)
PDFS = ROOT / "release_1_pdfs"
RECHECK = ROOT / "image_audit" / "recheck"
OUT_DIR = ROOT / "image_audit" / "fallback_mini"
OUT_DIR.mkdir(parents=True, exist_ok=True)

GPT_MODEL = "gpt-5.4-mini"
gpt = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=180)

HAS_VISUAL_CATS = {
    "photograph", "sketch", "diagram", "map",
    "chart_or_graph", "newspaper_clipping_illustration",
}

PROMPT = """You are auditing an image inside a US government UAP / FBI / military archive PDF page (war.gov public release, fully declassified). The original transcription system produced an Image: description that may be inaccurate.

Look at the image carefully and produce a SINGLE concise factual description of what is visually depicted, in this exact format:

*Image: <description>*

Be specific. If there are objects in a photograph, count them precisely. Distinguish between photographs, sketches, diagrams, maps, charts, forms, document scans. Note text labels, captions, and any visible numerical or letter annotations. Use neutral archival language. If the page has multiple distinct visual elements (e.g. a photograph plus a chart plus a stamp), produce one Image: line per element. If the page is purely text (no image, no photograph, no sketch, no diagram), respond with the single line: *No image content on this page.*

Do not include the surrounding text, only the Image: line(s)."""


def render_b64(pdf_path: Path, page_idx: int, dpi: int = 200, max_dim: int = 768) -> str:
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


def call_mini(b64: str) -> tuple[str, dict]:
    resp = gpt.chat.completions.create(
        model=GPT_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]}],
        reasoning_effort="none",
        max_completion_tokens=1500,
    )
    text = ((resp.choices or [None])[0].message.content or "").strip() if resp.choices else ""
    u = resp.usage
    usage = {
        "prompt_tokens": getattr(u, "prompt_tokens", 0),
        "completion_tokens": getattr(u, "completion_tokens", 0),
        "total_tokens": getattr(u, "total_tokens", 0),
    }
    ptd = getattr(u, "prompt_tokens_details", None)
    if ptd is not None:
        usage["cached_tokens"] = getattr(ptd, "cached_tokens", 0) or 0
    return text, usage


def collect_targets(mode: str = "has_visual"):
    """Walk recheck/ and pick records by filter mode.

    mode: "has_visual"
        original v0.1 filter: has_visual category + score in (0,1,2)
    mode: "missed_stamp_handwritten"
        the recheck flagged it (score 0/1) but our has_visual filter
        excluded it because mimo's strict pass categorized it as
        stamp_or_label_only / typed_text_only / etc. AND the page actually
        contains both stamps and handwriting (per orig tags or rerun text).
    """
    targets = []
    for stem_dir in sorted(RECHECK.iterdir()):
        if not stem_dir.is_dir():
            continue
        for jp in sorted(stem_dir.glob("page_*.json")):
            try:
                r = json.loads(jp.read_text())
            except Exception:
                continue
            cats = r.get("categories", [])
            hv = any(c in HAS_VISUAL_CATS for c in cats)
            score = (r.get("judge") or {}).get("score", 0)

            if mode == "has_visual":
                if not hv:
                    continue
                if score not in (0, 1, 2):
                    continue
            elif mode == "missed_stamp_handwritten":
                if hv:
                    continue
                if score not in (0, 1):
                    continue
                rerun = r.get("rerun_extract", {})
                rerun_text = " ".join(
                    (e.get("description", "") if isinstance(e, dict) else "")
                    for e in (rerun.get("elements", []) if isinstance(rerun, dict) else [])
                ).lower()
                orig_text = " ".join(r.get("original_image_tags", [])).lower()
                blob = rerun_text + " " + orig_text
                if not ("handwrit" in blob and "stamp" in blob):
                    continue
            else:
                raise ValueError(f"unknown mode: {mode}")

            targets.append({
                "pdf_stem": r.get("pdf_stem"),
                "page_num": r.get("page_num"),
                "categories": cats,
                "judge_score": score,
                "judge_reason": (r.get("judge") or {}).get("reason", ""),
                "original_image_tags": r.get("original_image_tags", []),
            })
    return targets


def process_one(target: dict, force: bool = False) -> dict:
    out_path = OUT_DIR / target["pdf_stem"] / f"page_{target['page_num']:03d}.json"
    if out_path.exists() and not force:
        try:
            return json.loads(out_path.read_text())
        except Exception:
            pass
    out_path.parent.mkdir(exist_ok=True)

    pdf_path = PDFS / f"{target['pdf_stem']}.pdf"
    if not pdf_path.exists():
        rec = {"status": "pdf_missing", **target}
        out_path.write_text(json.dumps(rec, ensure_ascii=False))
        return rec

    try:
        b64 = render_b64(pdf_path, target["page_num"] - 1)
    except Exception as e:
        rec = {"status": "render_err", "err": str(e), **target}
        out_path.write_text(json.dumps(rec, ensure_ascii=False))
        return rec

    try:
        gpt_desc, usage = call_mini(b64)
        status = "ok"
    except Exception as e:
        gpt_desc = ""
        usage = {}
        status = f"gpt_err: {str(e)[:200]}"

    rec = {
        "status": status,
        "pdf_stem": target["pdf_stem"],
        "page_num": target["page_num"],
        "categories": target["categories"],
        "judge_score": target["judge_score"],
        "judge_reason": target["judge_reason"],
        "original_image_tags": target["original_image_tags"],
        "gpt_mini_desc": gpt_desc,
        "gpt_mini_desc_len": len(gpt_desc),
        "usage": usage,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    out_path.write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--mode", choices=["has_visual", "missed_stamp_handwritten"], default="has_visual")
    args = ap.parse_args()

    targets = collect_targets(mode=args.mode)
    if args.limit:
        targets = targets[:args.limit]
    print(f"Targets (has_visual + s0/s1/s2): {len(targets)} pages", flush=True)

    done_count = 0
    ok_count = 0
    err_count = 0
    no_img_count = 0
    lock = threading.Lock()

    def progress(rec):
        nonlocal done_count, ok_count, err_count, no_img_count
        with lock:
            done_count += 1
            if rec.get("status") == "ok":
                ok_count += 1
                if "No image content" in rec.get("gpt_mini_desc", ""):
                    no_img_count += 1
            else:
                err_count += 1
            if done_count % 10 == 0 or done_count == len(targets):
                print(f"  {done_count}/{len(targets)} ok={ok_count} no_img={no_img_count} err={err_count}", flush=True)

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
                    err_count += 1
                try:
                    t = next(target_iter)
                    in_flight[ex.submit(process_one, t, args.force)] = True
                except StopIteration:
                    pass
            gc.collect()

    # Aggregate usage by reading all on-disk records (covers cached + fresh)
    total_prompt = 0
    total_completion = 0
    total_cached = 0
    counted = 0
    for stem_dir in sorted(OUT_DIR.iterdir()):
        if not stem_dir.is_dir():
            continue
        for jp in sorted(stem_dir.glob("page_*.json")):
            try:
                r = json.loads(jp.read_text())
            except Exception:
                continue
            u = r.get("usage") or {}
            total_prompt += u.get("prompt_tokens", 0)
            total_completion += u.get("completion_tokens", 0)
            total_cached += u.get("cached_tokens", 0)
            if u:
                counted += 1

    PRICE_INPUT = 0.75 / 1_000_000   # gpt-5.4-mini
    PRICE_CACHED = 0.075 / 1_000_000
    PRICE_OUTPUT = 4.50 / 1_000_000

    fresh_input = max(total_prompt - total_cached, 0)
    cost_input = fresh_input * PRICE_INPUT
    cost_cached = total_cached * PRICE_CACHED
    cost_output = total_completion * PRICE_OUTPUT
    cost_total = cost_input + cost_cached + cost_output

    summary = {
        "total_targets": len(targets),
        "ok": ok_count,
        "no_image_marker": no_img_count,
        "errors": err_count,
        "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "usage_records": counted,
        "tokens": {
            "prompt_total": total_prompt,
            "prompt_cached": total_cached,
            "prompt_fresh": fresh_input,
            "completion": total_completion,
        },
        "cost_usd": {
            "input_fresh": round(cost_input, 6),
            "input_cached": round(cost_cached, 6),
            "output": round(cost_output, 6),
            "total": round(cost_total, 6),
        },
        "model": GPT_MODEL,
        "pricing_per_million": {"input": 0.75, "cached_input": 0.075, "output": 4.50},
    }
    (OUT_DIR / "_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nSummary: {json.dumps(summary, indent=2)}")


if __name__ == "__main__":
    main()
