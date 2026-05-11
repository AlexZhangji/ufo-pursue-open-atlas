#!/usr/bin/env python3
"""Offline sanity check for the hybrid index that web/search.html serves.

Loads the same embeddings.f16.bin + documents.json the browser will use,
embeds a query with fastembed, computes BM25 + cosine, fuses via RRF,
prints the top results. If this looks bad, the browser version will look
just as bad — debug here first.

Run:
    python scripts/search_cli.py "flying saucer virginia 1949"
    python scripts/search_cli.py "apollo crew technical debriefing" --topk 5
"""

from __future__ import annotations
import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding

ROOT = Path(__file__).resolve().parent.parent
IDX_DIR = ROOT / "web" / "search_index"
MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384


def load_index():
    meta = json.loads((IDX_DIR / "meta.json").read_text(encoding="utf-8"))
    docs = json.loads((IDX_DIR / "documents.json").read_text(encoding="utf-8"))
    emb_buf = (IDX_DIR / "embeddings.f16.bin").read_bytes()
    vecs = np.frombuffer(emb_buf, dtype=np.float16).reshape(-1, meta["embed_dim"])
    return meta, docs, vecs


# ─── Tiny BM25 over the same fields the JS front-end indexes ──────────
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")

def tokenize(s: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(s or "")]

def build_corpus_tokens(docs: list[dict]) -> list[list[str]]:
    """Lexical fields, weighted by repetition so simple BM25 sees the boost
    pattern the browser MiniSearch applies via .searchOptions.boost."""
    out = []
    for d in docs:
        tokens = []
        if t := d.get("title"):           tokens.extend(tokenize(t) * 3)
        if a := d.get("agency"):          tokens.extend(tokenize(a) * 2)
        if loc := d.get("incident_location"): tokens.extend(tokenize(loc) * 2)
        for tag in (d.get("image_tags") or [])[:8]:
            tokens.extend(tokenize(tag) * 2)
        tokens.extend(tokenize(d.get("text") or "")[:1500])
        out.append(tokens)
    return out


def bm25_score(query_terms: list[str], corpus_tokens: list[list[str]],
               k1: float = 1.5, b: float = 0.75) -> np.ndarray:
    n = len(corpus_tokens)
    df = Counter()
    for toks in corpus_tokens:
        for t in set(toks):
            df[t] += 1
    avgdl = sum(len(toks) for toks in corpus_tokens) / max(n, 1)
    idf = {t: math.log((n - df[t] + 0.5) / (df[t] + 0.5) + 1) for t in df}
    scores = np.zeros(n, dtype=np.float32)
    for i, toks in enumerate(corpus_tokens):
        if not toks:
            continue
        tf = Counter(toks)
        dl = len(toks)
        s = 0.0
        for q in query_terms:
            if q not in tf:
                continue
            f = tf[q]
            s += idf.get(q, 0) * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avgdl))
        scores[i] = s
    return scores


def rrf(ranked_lists, k=60, topk=20):
    scores: dict[int, float] = {}
    for lst in ranked_lists:
        for rank, idx in enumerate(lst):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])[:topk]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", type=str, nargs="+")
    ap.add_argument("--topk", type=int, default=10)
    ap.add_argument("--show-bm25-only", action="store_true")
    ap.add_argument("--show-dense-only", action="store_true")
    args = ap.parse_args()
    query = " ".join(args.query)

    print(f"loading index from {IDX_DIR}")
    meta, docs, vecs = load_index()
    print(f"  {len(docs)} docs · {vecs.shape} fp16 · model {meta['model_name']}")

    print("\nembedding query...")
    embedder = TextEmbedding(model_name=MODEL_NAME)
    qvec = list(embedder.embed([query]))[0].astype(np.float32)
    qvec = qvec / max(np.linalg.norm(qvec), 1e-9)

    # Dense — vecs are already L2-normalized so dot == cosine.
    dense_scores = (vecs.astype(np.float32) @ qvec)
    dense_rank = np.argsort(-dense_scores)[:60].tolist()

    # BM25 over a lightweight tokenization of the same fields.
    print("computing BM25...")
    corpus_tokens = build_corpus_tokens(docs)
    qterms = tokenize(query)
    bm25_scores = bm25_score(qterms, corpus_tokens)
    bm25_rank = [int(i) for i in np.argsort(-bm25_scores)[:60] if bm25_scores[int(i)] > 0]

    if args.show_bm25_only:
        chosen = [(i, bm25_scores[i]) for i in bm25_rank[:args.topk]]
        label = "BM25"
    elif args.show_dense_only:
        chosen = [(i, dense_scores[i]) for i in dense_rank[:args.topk]]
        label = "DENSE"
    else:
        fused = rrf([bm25_rank, dense_rank], k=60, topk=args.topk)
        chosen = fused
        label = "RRF"

    print(f"\n── top {len(chosen)} {label} for: {query!r} ──")
    for rank, (i, sc) in enumerate(chosen, 1):
        d = docs[i]
        bm = bm25_scores[i]
        ds = dense_scores[i]
        print(f"\n[{rank}] {label}={sc:.4f}  bm25={bm:.2f}  cos={ds:.3f}")
        print(f"     {d.get('agency','?')[:24]:<24} {d.get('year','?')!s:<6} {(d.get('incident_location') or '—')[:30]}")
        print(f"     {d.get('title','')[:90]}")
        page = f"p.{d.get('page_num','?')}/{d.get('total_pages','?')}"
        print(f"     {d.get('record_id','')[:60]}  {page}")
        # First text line with one of the query terms, if any.
        text = (d.get("text") or "").replace("\n", " ")
        low = text.lower()
        snippet_start = 0
        for q in qterms:
            p = low.find(q)
            if p > 0:
                snippet_start = max(0, p - 40); break
        snippet = text[snippet_start:snippet_start + 180].strip()
        if snippet:
            print(f"     “{snippet}…”")


if __name__ == "__main__":
    main()
