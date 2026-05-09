#!/usr/bin/env python3
"""Replace original *Image: ...* tags in mimo_processed/ pages with gpt-5.4-mini descriptions
from image_audit/fallback_mini/.

Strategy per page:
  - find ALL *Image: ...* matches in markdown
  - if gpt_mini_desc == "*No image content on this page.*" (or a "no image"
    variant), DELETE all matches (mimo originally false-positived an image)
  - else, REPLACE first match with gpt_mini_desc verbatim, DELETE subsequent matches
  - tidy up double-blank-lines created by deletion
"""

from __future__ import annotations
import os, re, json, sys
from pathlib import Path

ROOT = Path(os.environ.get("PURSUE_ROOT") or Path(__file__).resolve().parent.parent)
PROCESSED = ROOT / "mimo_processed"
FALLBACK = ROOT / "image_audit" / "fallback_mini"

IMG_RE = re.compile(r'\*Image:\s*(.+?)\*', re.DOTALL)
NO_IMG_RE = re.compile(r'\*No image content on this page\.\*', re.IGNORECASE)


def is_no_image_marker(s: str) -> bool:
    return bool(NO_IMG_RE.search(s.strip())) and not IMG_RE.search(s)


def apply_one(md_path: Path, gpt_desc: str) -> dict:
    text = md_path.read_text(encoding='utf-8', errors='replace')
    matches = list(IMG_RE.finditer(text))
    if not matches:
        return {"action": "no_match", "n_orig": 0}

    no_img = is_no_image_marker(gpt_desc)
    new_parts = []
    last_end = 0
    for i, m in enumerate(matches):
        new_parts.append(text[last_end:m.start()])
        if i == 0 and not no_img:
            new_parts.append(gpt_desc.strip())
        last_end = m.end()
    new_parts.append(text[last_end:])
    new_text = "".join(new_parts)

    # tidy: collapse 3+ consecutive blank lines into 2
    new_text = re.sub(r'\n{3,}', '\n\n', new_text)

    md_path.write_text(new_text, encoding='utf-8')
    return {
        "action": "no_image_deleted" if no_img else "replaced",
        "n_orig": len(matches),
    }


def main():
    n_replaced = 0
    n_no_image_deleted = 0
    n_no_match = 0
    n_pdf_missing = 0
    n_skip_err = 0
    multi_orig = 0
    diff_samples = []

    for stem_dir in sorted(FALLBACK.iterdir()):
        if not stem_dir.is_dir():
            continue
        for jp in sorted(stem_dir.glob("page_*.json")):
            try:
                r = json.loads(jp.read_text())
            except Exception:
                n_skip_err += 1
                continue
            if r.get("status") != "ok":
                n_skip_err += 1
                continue
            stem = r["pdf_stem"]
            page_num = r["page_num"]
            gpt_desc = r.get("gpt_mini_desc", "").strip()
            if not gpt_desc:
                n_skip_err += 1
                continue

            md_path = PROCESSED / stem / f"page_{page_num:03d}.md"
            if not md_path.exists():
                n_pdf_missing += 1
                continue

            res = apply_one(md_path, gpt_desc)
            if res["action"] == "replaced":
                n_replaced += 1
            elif res["action"] == "no_image_deleted":
                n_no_image_deleted += 1
            elif res["action"] == "no_match":
                n_no_match += 1
            if res["n_orig"] > 1:
                multi_orig += 1

            if len(diff_samples) < 5 and res["action"] in ("replaced", "no_image_deleted"):
                diff_samples.append({
                    "stem": stem,
                    "page": page_num,
                    "action": res["action"],
                    "n_orig_tags": res["n_orig"],
                    "gpt_desc": gpt_desc[:200],
                })

    print(json.dumps({
        "replaced": n_replaced,
        "no_image_deleted": n_no_image_deleted,
        "no_match_in_md": n_no_match,
        "pdf_missing": n_pdf_missing,
        "skipped_err": n_skip_err,
        "pages_with_multi_orig_tags": multi_orig,
        "diff_samples": diff_samples,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
