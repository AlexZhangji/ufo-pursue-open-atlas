#!/usr/bin/env python3
"""Batch evaluator for candidate UI example queries.

Loads the search index + embedder once, runs a list of candidate
queries, prints compact top-K so we can eyeball which queries make
hybrid retrieval look good. Reuses the same RRF logic as the JS UI.

Usage:
    python scripts/search_batch.py
"""

from __future__ import annotations
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
TOPK = 5

# Candidates — leaning toward queries where dense should beat BM25.
# After running we keep the 5-6 that look best for the UI's "Try:" row.
CANDIDATES = [
    "how fast did the object move",
    "object moving very fast estimated speed",
    "low-altitude metallic disc spinning",
    "silent hovering craft witness account",
    "object emitted bright glowing light",
    "object made no sound",
    "pilot fear of being ridiculed",
    "radar contact unable to track",
    "intelligence assessment of Soviet capability",
    "describe maneuvering ability of the craft",
    "newspaper clipping flying saucer",   # keyword-heavy baseline
    "apollo astronaut debriefing",        # keyword-heavy baseline
]


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")

def tokenize(s): return [t.lower() for t in TOKEN_RE.findall(s or "")]

def build_corpus_tokens(docs):
    out = []
    for d in docs:
        toks = []
        if t := d.get("title"):           toks.extend(tokenize(t) * 3)
        if a := d.get("agency"):          toks.extend(tokenize(a) * 2)
        if loc := d.get("incident_location"): toks.extend(tokenize(loc) * 2)
        for tag in (d.get("image_tags") or [])[:8]:
            toks.extend(tokenize(tag) * 2)
        toks.extend(tokenize(d.get("text") or "")[:1500])
        out.append(toks)
    return out

def bm25_scores(query_terms, corpus_tokens, df, idf, avgdl, k1=1.5, b=0.75):
    n = len(corpus_tokens)
    scores = np.zeros(n, dtype=np.float32)
    for i, toks in enumerate(corpus_tokens):
        if not toks: continue
        tf = Counter(toks); dl = len(toks); s = 0.0
        for q in query_terms:
            if q not in tf: continue
            f = tf[q]
            s += idf.get(q, 0) * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avgdl))
        scores[i] = s
    return scores

def rrf(rank_lists, k=60, topk=TOPK):
    scores = {}
    for lst in rank_lists:
        for rank, idx in enumerate(lst):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])[:topk]


def main():
    print(f"loading index from {IDX_DIR}")
    meta = json.loads((IDX_DIR / "meta.json").read_text(encoding="utf-8"))
    docs = json.loads((IDX_DIR / "documents.json").read_text(encoding="utf-8"))
    vecs = np.frombuffer((IDX_DIR / "embeddings.f16.bin").read_bytes(),
                         dtype=np.float16).reshape(-1, meta["embed_dim"]).astype(np.float32)
    print(f"  {len(docs)} docs · {vecs.shape}")

    print(f"\nbuilding BM25 inverted index (once)...")
    corpus_tokens = build_corpus_tokens(docs)
    df = Counter()
    for toks in corpus_tokens:
        for t in set(toks): df[t] += 1
    n = len(corpus_tokens)
    avgdl = sum(len(t) for t in corpus_tokens) / max(n, 1)
    idf = {t: math.log((n - df[t] + 0.5) / (df[t] + 0.5) + 1) for t in df}

    print(f"loading embedder: {MODEL_NAME}")
    embedder = TextEmbedding(model_name=MODEL_NAME)

    print(f"\n{'═' * 78}")
    for q in CANDIDATES:
        print(f"\n▌ QUERY: {q!r}")
        qvec = list(embedder.embed([q]))[0].astype(np.float32)
        qvec = qvec / max(np.linalg.norm(qvec), 1e-9)

        dense = vecs @ qvec
        dense_rank = [int(i) for i in np.argsort(-dense)[:60].tolist()]

        qterms = tokenize(q)
        bm = bm25_scores(qterms, corpus_tokens, df, idf, avgdl)
        bm_rank = [int(i) for i in np.argsort(-bm)[:60].tolist() if bm[int(i)] > 0]

        fused = rrf([bm_rank, dense_rank])

        # How much "AI-only" lift is there in top-K?
        bm_top_set = set(bm_rank[:TOPK])
        dense_top_set = set(dense_rank[:TOPK])
        fused_ids = [i for i, _ in fused]

        ai_only = [i for i in fused_ids if i not in bm_top_set and i in dense_top_set]
        bm_only = [i for i in fused_ids if i in bm_top_set and i not in dense_top_set]
        overlap = [i for i in fused_ids if i in bm_top_set and i in dense_top_set]

        print(f"  hybrid {len(fused_ids)} = both {len(overlap)} · AI-only {len(ai_only)} · keyword-only {len(bm_only)}")

        for rank, (i, sc) in enumerate(fused[:TOPK], 1):
            d = docs[i]
            label = (
                'BOTH' if i in bm_top_set and i in dense_top_set
                else 'AI  ' if i in dense_top_set
                else 'KEY ' if i in bm_top_set
                else 'rrf '
            )
            agency = (d.get("agency") or "?")[:10]
            year = d.get("year")
            title = (d.get("title") or "")[:62]
            print(f"  [{rank}] {label} cos={dense[i]:.3f} bm25={bm[i]:5.2f}  {agency:<10} {year!s:<6} {title}")
            txt = (d.get("text") or "").replace("\n", " ")
            low = txt.lower()
            best = 0
            for qt in qterms:
                p = low.find(qt)
                if p > 0: best = max(0, p - 30); break
            snip = txt[best:best + 130].strip()
            print(f"          “{snip}…”")


if __name__ == "__main__":
    main()
