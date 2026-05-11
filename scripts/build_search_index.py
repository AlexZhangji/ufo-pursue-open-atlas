#!/usr/bin/env python3
"""Build the client-side hybrid search index used by web/search.html.

Pipeline:
  corpus.jsonl
      │
      ├──→ embed each page with BAAI/bge-small-en-v1.5 (384d, L2-normalized)
      │    via fastembed (ONNX, no torch). Same model the JS front-end will
      │    load through transformers.js for query embedding, so the vector
      │    spaces line up exactly.
      │
      └──→ strip per-page metadata down to what the UI actually renders
           and ship as documents.json. minisearch indexes this in-browser
           for the BM25 side of the hybrid.

Outputs (under web/search_index/):
  embeddings.f16.bin   Raw Float16, shape (N_DOCS, 384), L2-normalized.
                       In JS: read as Uint16Array → reinterpret → cosine
                       is just a dot product since norms are 1.
  documents.json       Array<{id, record_id, pdf_stem, page_num, title,
                       agency, record_type, year, incident_location,
                       text, image_tags, source_url, thumb_path}>.
  meta.json            Build metadata: model, dim, n_docs, built_at.

Run from repo root (uv venv must have fastembed installed):
    python scripts/build_search_index.py
"""

from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus.jsonl"
OUT_DIR = ROOT / "web" / "search_index"

MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384
# bge-small accepts 512 tokens ≈ 1500-2000 chars. Past that the encoder
# truncates anyway — leaving headroom for the title/agency/tags prefix.
MAX_TEXT_CHARS = 1500

# Fields kept in documents.json. Anything not in this list gets dropped
# to keep the wire payload lean. Order is preserved when serializing.
DOC_FIELDS = (
    "id",                       # row index → joins to embeddings.f16.bin
    "record_id",
    "pdf_stem",
    "page_num",
    "total_pages",
    "title",
    "agency",
    "record_type",
    "year",
    "incident_location",
    "incident_date_iso",
    "text",
    "image_tags",
    "source_url",
    "thumb_path",
)


def build_embed_text(rec: dict) -> str:
    """Compose the string fed into BGE.

    Prefix with title / agency / location so geographic and bureaucratic
    cues lift into the dense vector — these are exactly the things users
    type as queries ("FBI virginia 1949", "NASA apollo debriefing").
    """
    parts: list[str] = []
    if t := rec.get("title"):
        parts.append(f"Title: {t}.")
    if a := rec.get("agency"):
        parts.append(f"Agency: {a}.")
    if loc := rec.get("incident_location"):
        parts.append(f"Location: {loc}.")
    if yr := rec.get("year"):
        parts.append(f"Year: {yr}.")
    body = (rec.get("text") or "")[:MAX_TEXT_CHARS]
    parts.append(body)
    if tags := rec.get("image_tags"):
        # image_tags carry the VLM's description of any photo/diagram on
        # the page — high-signal for visual queries like "newspaper
        # clipping flying saucer" that wouldn't match the OCR text.
        parts.append("Images: " + " | ".join(tags[:5]))
    return " ".join(parts)


def thumb_path_for(rec: dict) -> str | None:
    """Map page_image_path → web/thumbs/-relative path used by the UI.
    Returns None for records that have no rendered page (shouldn't happen
    after v0.1 but we guard for it)."""
    rel = rec.get("page_image_path")
    if not rel:
        return None
    # 'release_1_renders/<stem>/page_NNN.jpg' → 'thumbs/<stem>/page_NNN.jpg'
    parts = Path(rel).parts
    if parts and parts[0] == "release_1_renders":
        parts = parts[1:]
    # Force .jpg extension since build_thumbnails.py always writes JPEG.
    p = Path(*parts).with_suffix(".jpg")
    return f"thumbs/{p.as_posix()}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    print(f"loading corpus: {CORPUS}")
    rows: list[dict] = []
    with CORPUS.open(encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    print(f"  {len(rows)} pages")

    print(f"\nloading embedder: {MODEL_NAME}")
    embedder = TextEmbedding(model_name=MODEL_NAME)

    texts_to_embed = [build_embed_text(r) for r in rows]

    print(f"embedding {len(texts_to_embed)} docs (batch={args.batch_size})...")
    t0 = time.time()
    vecs = np.empty((len(texts_to_embed), EMBED_DIM), dtype=np.float32)
    i = 0
    for vec in embedder.embed(texts_to_embed, batch_size=args.batch_size):
        vecs[i] = vec
        i += 1
        if i % 500 == 0:
            elapsed = time.time() - t0
            rate = i / elapsed
            eta = (len(texts_to_embed) - i) / rate
            print(f"  [{i}/{len(texts_to_embed)}] {rate:.0f} docs/s · ETA {eta:.0f}s")
    elapsed = time.time() - t0
    print(f"  done in {elapsed:.1f}s ({len(texts_to_embed)/elapsed:.0f} docs/s)")

    # Sanity: bge-small returns already-normalized vectors, but renormalize
    # defensively so the JS side can use plain dot product without worry.
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vecs = vecs / norms

    args.out.mkdir(parents=True, exist_ok=True)

    # ---- embeddings.f16.bin ----
    emb_f16 = vecs.astype(np.float16)
    emb_path = args.out / "embeddings.f16.bin"
    emb_f16.tofile(emb_path)
    emb_mb = emb_path.stat().st_size / 1024 / 1024
    print(f"\nwrote {emb_path.name}: {emb_f16.shape} fp16, {emb_mb:.1f} MB")

    # ---- documents.json ----
    docs_out: list[dict] = []
    for idx, rec in enumerate(rows):
        d = {f: None for f in DOC_FIELDS}
        d["id"] = idx
        d["thumb_path"] = thumb_path_for(rec)
        for k in DOC_FIELDS:
            if k in ("id", "thumb_path"):
                continue
            d[k] = rec.get(k)
        docs_out.append(d)
    docs_path = args.out / "documents.json"
    with docs_path.open("w", encoding="utf-8") as f:
        json.dump(docs_out, f, ensure_ascii=False)
    docs_mb = docs_path.stat().st_size / 1024 / 1024
    print(f"wrote {docs_path.name}: {len(docs_out)} docs, {docs_mb:.1f} MB")

    # ---- meta.json ----
    meta = {
        "model_name": MODEL_NAME,
        "embed_dim": EMBED_DIM,
        "n_docs": len(rows),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "max_text_chars_in_embed": MAX_TEXT_CHARS,
        "embedding_dtype": "float16",
        "embedding_layout": "row-major (n_docs, embed_dim), L2-normalized",
        "doc_fields": list(DOC_FIELDS),
    }
    meta_path = args.out / "meta.json"
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(f"wrote {meta_path.name}")

    print(f"\nall outputs in {args.out}")


if __name__ == "__main__":
    main()
