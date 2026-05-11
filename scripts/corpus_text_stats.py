#!/usr/bin/env python3
"""Distribution of per-page text length in corpus.jsonl, so we can decide
whether chunking is needed or pages already fit comfortably in BGE's
512-token context window.

Token count is approximated by the tokenizer fastembed actually uses for
BGE — same path the index goes through, so the numbers reflect what the
encoder actually sees.

Run from repo root:
    python scripts/corpus_text_stats.py
"""

from __future__ import annotations
import json
from pathlib import Path
from collections import Counter

import numpy as np
from fastembed import TextEmbedding

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus.jsonl"
MODEL_NAME = "BAAI/bge-small-en-v1.5"


def build_embed_text(rec: dict) -> str:
    """Same prefix concat the index actually embeds (build_search_index.py)."""
    parts: list[str] = []
    if t := rec.get("title"):           parts.append(f"Title: {t}.")
    if a := rec.get("agency"):          parts.append(f"Agency: {a}.")
    if loc := rec.get("incident_location"): parts.append(f"Location: {loc}.")
    if yr := rec.get("year"):           parts.append(f"Year: {yr}.")
    parts.append((rec.get("text") or "")[:1500])
    if tags := rec.get("image_tags"):
        parts.append("Images: " + " | ".join(tags[:5]))
    return " ".join(parts)


def pct(xs, p):
    return float(np.percentile(xs, p))


def hist_text(xs, bins, width=30):
    counts, edges = np.histogram(xs, bins=bins)
    mx = max(counts) or 1
    out = []
    for i, c in enumerate(counts):
        bar = '█' * int(width * c / mx)
        out.append(f"  {edges[i]:>6.0f} – {edges[i+1]:>6.0f}  {c:>5d}  {bar}")
    return "\n".join(out)


def main():
    print(f"loading {CORPUS}")
    rows = []
    with CORPUS.open(encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    print(f"  {len(rows)} pages\n")

    # Raw text length (chars).
    raw_chars   = np.array([len(r.get("text") or "")              for r in rows])
    body_chars  = np.array([len((r.get("text") or "")[:1500])     for r in rows])  # post-truncation
    embed_chars = np.array([len(build_embed_text(r))              for r in rows])  # what the encoder gets

    print("── raw page text (chars) ──")
    print(f"  mean {raw_chars.mean():.0f}  median {np.median(raw_chars):.0f}  "
          f"p90 {pct(raw_chars,90):.0f}  p99 {pct(raw_chars,99):.0f}  "
          f"max {raw_chars.max()}")
    print(f"  pages over 1500 chars (truncated): "
          f"{int((raw_chars > 1500).sum())} / {len(rows)} "
          f"({100 * (raw_chars > 1500).mean():.1f}%)")
    print(f"  pages over 4000 chars: "
          f"{int((raw_chars > 4000).sum())} / {len(rows)} "
          f"({100 * (raw_chars > 4000).mean():.1f}%)\n")

    print(f"── chars actually embedded (after prefix + truncation) ──")
    print(f"  mean {embed_chars.mean():.0f}  median {np.median(embed_chars):.0f}  "
          f"p90 {pct(embed_chars,90):.0f}  p99 {pct(embed_chars,99):.0f}  "
          f"max {embed_chars.max()}\n")

    # Now tokenize a sample to get real token counts.
    print(f"── BGE tokenization (sample of 1000 pages) ──")
    embedder = TextEmbedding(model_name=MODEL_NAME)
    # fastembed wraps a tokenizer at embedder.model.tokenizer
    tok = embedder.model.tokenizer
    sample_idx = np.random.RandomState(42).choice(len(rows), size=min(1000, len(rows)), replace=False)
    sample_texts = [build_embed_text(rows[i]) for i in sample_idx]
    tok_counts = np.array([len(tok.encode(t).ids) for t in sample_texts])
    print(f"  mean {tok_counts.mean():.0f}  median {np.median(tok_counts):.0f}  "
          f"p90 {pct(tok_counts,90):.0f}  p99 {pct(tok_counts,99):.0f}  "
          f"max {tok_counts.max()}")
    print(f"  pages at or beyond BGE 512-token cap (truncated by encoder):")
    print(f"    {int((tok_counts >= 512).sum())} / {len(tok_counts)} "
          f"({100 * (tok_counts >= 512).mean():.1f}%)")

    print(f"\n── histogram of token counts (sample of 1000) ──")
    print(hist_text(tok_counts, bins=20))


if __name__ == "__main__":
    main()
