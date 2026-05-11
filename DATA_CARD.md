# Data Card - PURSUE Open Atlas v0.2

This card documents how the dataset was built, what we know about its
quality, and where users should be careful. We aim for radical
transparency: every step that touches the data is described here, and
every artifact (recheck logs, GPT outputs, original mimo extractions) is
preserved alongside the corpus so anyone can audit the pipeline.

> **v0.2 update.** Added a fully client-side keyword + AI hybrid search
> (MiniSearch BM25 + `bge-small-en-v1.5` dense, fused with per-query
> min-max normalize). Live at <https://ufo.gpt2077.com/search.html>.
> Source code, schema, and rebuild scripts at
> <https://github.com/AlexZhangji/ufo-pursue-open-atlas>. No changes to
> the corpus contents — same 4,153 pages, same fields, same license.

---

## 1. Source

**PURSUE Release 01**, published 2026-05-08 by the U.S. Department of
War (formerly DoD), at [war.gov/UFO](https://www.war.gov/UFO/). Largest
single declassification of UAP material in U.S. government history at
time of release: 161 records spanning ~80 years.

Source artifacts:
- 130 PDFs / images
- 28 mp4 videos hosted on DVIDS (out of scope for v1)
- 1 NASA Gemini 7 audio clip (out of scope for v1)

All source documents are public domain under 17 U.S.C. Section 105
(works of the U.S. federal government).

Master index downloaded from war.gov as CSV (`uap-csv.csv`). PDF URL
pattern: `https://www.war.gov/medialink/ufo/release_1/<filename>`.
Akamai/edgesuite blocks non-browser clients; download script uses
browser headers to bypass.

---

## 2. What v1 covers

| Element | Status |
|---|---|
| Side-by-side dataset viewer (PDF page next to extracted Markdown) | done |
| VLM extraction to per-page Markdown | done (~5,300 pages) |
| Image-tag audit + GPT-mini fallback | done (515 pages re-described across two batches) |
| Per-page rendered JPEG (200 DPI, q=88, max 2000 px) | done |
| Single-file corpus.jsonl with `page_image_path` | scripted; build with one command |
| Metadata atlas (CSV → cleaned + geocoded JSON) | done |
| PDF / IMG download (130 files) | done |
| **Hybrid keyword + AI search UI** (BM25 + bge-small-en-v1.5, browser-side) | done (v0.2) |
| **400 px page thumbnails for search previews** (4,153 JPEGs · ~125 MB) | done (v0.2) |
| Video transcription | deferred to v3 |
| NASA audio transcription | deferred to v3 |

The viewer is listed first deliberately. It is the most important
quality gate this release provides over the raw government dump:
without a way to verify any single page against its source PDF in one
click, an "open dataset" is just a bigger pile of files where silent
extraction errors can hide indefinitely. Every other piece exists to
make the viewer trustworthy and useful.

---

## 3. Pipeline

```
war.gov/UFO + DVIDS  ─►  download_from_csv.py  ─►  release_1_pdfs/ (raw)
                                                       │
                                ┌──────────────────────┼────────────────────┐
                                │                      │                    │
                       prep_data.py            run_vlm_v3.py        download_videos.sh
                                │                      │                    │
                                ▼                      ▼                    ▼
                       web/data.json          mimo_processed/         (deferred)
                       (cleaned metadata)     (Markdown + meta)
                                                       │
                                                       ▼
                                              recheck_images.py
                                                       │
                                                       ▼
                                              run_fallback_mini.py
                                                       │
                                                       ▼
                                              apply_mini_replacements.py
                                                       │
                                                       ▼
                                              corpus.jsonl
```

Every extraction artifact carries a `_meta.json` with sha256 of source,
extraction model, prompt version, DPI, and timestamps.

---

## 4. VLM extraction

**Model:** `mimo-v2.5` (Xiaomi MiMo, accessed via Token Plan endpoint
`https://token-plan-sgp.xiaomimimo.com/v1`)

**Why MiMo:** strong on archival / multilingual document parsing, fast
enough for a 5,300-page corpus, and a documented track record on
typewriter / handwritten / mixed-language inputs.

**Prompt version:** `v3.1-uap-archive`. The full prompt is in
`pipeline/run_vlm_v3.py`. It instructs the model to emit Markdown that
preserves the following classes of source-page content:

- **Structural text** — headings, body paragraphs, numbered + bulleted
  lists, block quotes
- **Tables** — form fields, distribution lists, signature blocks, and
  any tabular content rendered as proper Markdown tables
- **Classification banners** — `## UNCLASSIFIED` / `## CONFIDENTIAL` /
  `## SECRET` / `## RESTRICTED` etc. emitted as Markdown headings
  when visible at the top, bottom, or as a stamp on the page
- **Image / visual content** — inline `*Image: <factual
  description>*` blocks for every photograph, sketch, diagram, map,
  chart, newspaper-clipping illustration, or other graphical element
- **Rubber stamps + ink stamps** — quoted verbatim and tagged inline
  (e.g. *Stamp: "DECLASSIFIED · NND 857013"*)
- **Handwritten annotations** — preserved as inline italics with a
  `*Handwritten:*` prefix where they appear in the original page flow
- **Redactions** — black-bar redactions noted as `[REDACTED]` or
  described in surrounding context
- **Margin annotations + page numbering** — kept as italic asides
  rather than dropped

**Render parameters:** 200 DPI, max dimension 2000 px (1500 for the
recheck pass), JPEG quality 85-92 depending on stage.

**Concurrency:** sliding-window 4 (was 10 in early runs; reduced after
mimo Token Plan rate limits caused a long tail of 429 errors and one
VPS memory spike).

**Resumability:** every page write is atomic; re-running skips finished
pages. `_meta.json` records which pages succeeded.

---

## 5. Image-tag audit

This is the most consequential quality step in v0.1. The first VLM pass
produced `*Image: ...*` tags that, on spot-check, sometimes:

- mis-counted figures (one mummy described as "three figures")
- fabricated specific names ("Willard H. Miller, seated") not visible in
  the page
- mis-categorized newspaper-clipping advertisements as photographs of
  the advertised content (one carpet ad was called "a textured carpet
  photograph")
- read different verbatim text in stamps than was actually present

We ran a structured audit on every page with at least one image tag:

### Stage 1 - recheck (`recheck_images.py`)

For each of 1,236 pages with image tags, the same MiMo model was called
twice on the rendered page:

1. **Strict re-extract**: a tighter prompt that asks for one record per
   visual element with categorical tag (`photograph`, `sketch`,
   `diagram`, `map`, `chart_or_graph`, `newspaper_clipping_illustration`,
   `stamp_or_label_only`, `typed_text_only`, `blank_or_back_of_page`,
   `redacted_only`).
2. **Judge call**: the same MiMo model is given the original `*Image:*`
   description and the new strict description, and asked to score
   factual consistency 1-3 with explicit hallucination detection rules.

Score distribution across 1,236 pages:

| Score | Meaning | Count | Share |
|---|---|---|---|
| 3 | factually consistent | 225 | 18% |
| 2 | mostly consistent | 388 | 31% |
| 1 | factually inconsistent | 551 | 45% |
| 0 | extract failed / parse error | 72 | 6% |

The high s1 share is misleading on its own: many s1 pages are pages
where mimo originally over-described a "stamp" or "typed memo" as
something visual; the second pass correctly classifies them as
`stamp_or_label_only` or `typed_text_only`, the judge sees the
disagreement as inconsistent. These pages do not need re-description,
just pruning.

### Stage 2 - has-visual filter

A page is flagged for GPT re-description only when the second-pass
category is one of `photograph`, `sketch`, `diagram`, `map`,
`chart_or_graph`, or `newspaper_clipping_illustration` AND the judge
score is 0, 1, or 2.

This narrowed the queue from 731 (any-disagreement) to **263 pages**.

### Stage 3 - gpt-5.4-mini re-description

The 263 flagged pages were re-described by `gpt-5.4-mini` (OpenAI, May
2026) using the same `*Image: <description>*` output format.

| Metric | Value |
|---|---|
| Pages | 263 |
| Model | `gpt-5.4-mini` (OpenAI, May 2026 snapshot) |
| Errors | 0 |
| Render input | 200 DPI page JPEG, max 1500 px |
| RSS peak | 742 MB at concurrency 4 |
| Wall-clock | ~10 min |

Per-page raw GPT outputs (with token-usage breakdown) are preserved in
`image_audit/fallback_mini/<stem>/page_NNN.json`.

### What changed

The `apply_mini_replacements.py` script replaces the original `*Image:*`
block(s) on each of the 263 pages with the GPT-mini output. 68 of those
263 pages had multiple original `*Image:*` tags from the first VLM pass.
On those pages the GPT prompt asked for a complete page-level
description, and the resulting single block replaces the first original
tag while the remaining tags are removed. **Downstream users should be
aware**: on these 68 pages, the per-tag granularity of the original
mimo extraction is lost, in exchange for a single more accurate
description that covers all visual elements on the page. The original
per-tag descriptions are preserved in
`image_audit/recheck/<stem>/page_NNN.json#original_image_tags` for
anyone who needs to recover them.

A backup of the pre-replacement Markdown is preserved at
`mimo_processed.bak.20260508/` (not in git, regeneratable from the
audit artifacts and the original mimo run).

### Stage 4 - extended audit batch (252 missed stamp+handwritten pages)

The Stage-2 has-visual filter excluded a long tail of pages where
mimo's strict re-extract categorized the page as `stamp_or_label_only`
or `typed_text_only`, but the page actually contained both rubber
stamps AND handwriting / sketches. mimo's first-pass image tag in
those cases often misclassified rubber stamps as handwritten margin
notes (e.g. an FBI 1947 letter to Hoover where mimo called the
"G.I.R." stamp and "ANONYMOUS COMPILATION" rubber stamp
"handwritten").

A second fallback batch was run with mode `--missed_stamp_handwritten`
on `pipeline/run_fallback_mini.py`, targeting the 252 pages flagged
score 0/1 + `hallucination_suspected = true` that the Stage-2 filter
had dropped. `max_dim` was reduced from 1500 to 768 px (same effective
quality on archival pages, ~60% input-token reduction).

| Metric | Value |
|---|---|
| Pages | 252 |
| Model | `gpt-5.4-mini` (OpenAI, May 2026 snapshot) |
| Render input | 200 DPI page JPEG, max **768 px** (down from 1500 px in Stage 3) |
| Errors | 0 |
| Cumulative re-described pages | 515 / 1,236 image-tag pages (42%) |

`apply_mini_replacements.py` is idempotent: it picked up the new 252
descriptions and left the prior 263 unchanged.

### Cumulative fallback set

After both batches, **515 pages** carry `image_tag_source =
"gpt-5.4-mini-2026"` and the remaining 721 image-tag pages keep
their `mimo-v2.5` first-pass description.

---

## 6. Page renders + multimodal parquet shards

Every PDF page (and every standalone image record) is shipped as a
200 DPI JPEG so downstream consumers can train multimodal models, run
document VQA, or audit a VLM extraction against the visual source
without re-running the rendering pipeline.

| Parameter | Value |
|---|---|
| Format | JPEG q=88 for VLM-rendered PDF pages; native JPG/PNG for the 14 standalone image records |
| DPI | 200 |
| Max dimension cap | 2000 px (longer axis) |
| Total size | ~2.0 GB across 4,153 pages |
| Render version | `v1-200dpi-cap2000-jpeg88` (bumped on parameter change) |
| Reproducibility | `python scripts/render_pages.py -j 4` |

JPEG q=88 was chosen over PNG: PNG of an FBI typewriter scan with
photo-grain noise produces 5+ MB per page; JPEG q=88 lands at
~400-500 KB per page with no visible quality loss for OCR / VLM use.
The 14 standalone image records (8 FBI photos + 6 NASA Apollo)
keep their native format — re-encoding 2.5 MB JPGs into PNGs bloats
them ~12x for no benefit.

### How they ship

The renders go out as **5 parquet shards** with image bytes embedded
inline, named `pages-{idx:05d}-of-00005.parquet`. Each shard ~400 MB,
~830 rows, every row carrying the same fields as `corpus.jsonl` plus
an `image` column typed as `datasets.Image()`.

| Reason | Detail |
|---|---|
| **No `cast_column` step** | `load_dataset(..., "pages")` returns `PIL.Image` directly |
| **HF dataset viewer renders natively** | parquet with `Image()` features is the canonical multimodal format |
| **Friendly to Git LFS** | 5 LFS objects vs 4,153 tiny files — no API rate-limit issues |
| **Sharded** | 5 × ~400 MB stays inside HF's per-shard recommendations and parallel-loads |

Reproducibility: `python scripts/build_parquet_shards.py`.

The render artifact is **separate from the VLM render** that produced
the Markdown extraction (mimo's internal renderer). Both pin the same
200 DPI / max 2000 px parameters, so visual content seen by the VLM at
extraction time matches what shipped here.

---

## 7. Known limitations

1. **515 / 1,236 image-tag pages were re-described, not 1,236.** The
   remaining 721 pages keep their original mimo-v2.5 image tags. The
   audit suggests most of these are correct (s3 + s2-without-hallucination
   + non-visual pages), but spot-check before relying on small-sample
   analysis.

2. **GPT-mini is more conservative.** Side-by-side review showed GPT
   sometimes drops correct specifics that mimo had (one photograph of a
   mechanical part lost the "5-bladed propeller" detail when GPT
   rewrote it as "circular mechanical part"). When mimo and GPT agreed,
   we trusted mimo. When they disagreed and mimo was specific without
   visible source text to back it, we trusted GPT.

3. **No human in the loop.** Both passes are LLM. Verification by
   subject-matter experts is left to downstream users.

4. **OCR layer of source PDFs is mostly empty.** Sweep with
   `pymupdf.page.get_text()` across all 4,153 pages: **3,595 pages
   (86.6%) return zero native text** because they are image-only
   scans; another 35 (0.8%) return <50 chars (just stamp text or page
   numbers); only 523 (12.6%) have ≥50 chars of native text, and ~9%
   of those carry detectable OCR glitches (`COMFIDEMTIAL`, `E.0.`
   instead of `E.O.`, broken `fl` ligatures inside words). The FBI
   62-HQ-83894 case file alone is ~2,000 pages, **all 100% empty
   native text**. For these pages the VLM is the only source of text.
   For the 12.6% with non-empty text, the VLM still re-renders and
   re-extracts (not the embedded text), which trades fidelity for
   uniformity (consistent Markdown structure across digital and
   scanned pages, image content surfaced inline as `*Image: ...*`
   blocks).

5. **Metadata corrections are limited to the four locations and one
   date that we caught in spot-checks** (see
   [corrections.json](./corrections.json)). The CSV almost certainly
   contains other errors we have not yet found.

6. **Year inference for N/A dates uses the filename pattern only.** 56
   records had `Incident Date = N/A` in the CSV but a year embedded in
   the filename (e.g. `nasa-uap-d4-apollo-11-...-1969`). We extract that
   year and label it `year_inferred = true`. We do not infer month or
   day; those records are placed at June 15 of the inferred year for
   atlas display purposes only.

7. **Geocoding is a curated lookup table, not a service call.** New
   locations in future tranches need to be added by hand to
   `web/prep_data.py:GEOCODE`.

8. **Not a substitute for the source PDF.** This corpus is a tool for
   discovery, indexing, and ML, not a forensic OCR replacement. Every
   page is a VLM re-rendering, not a verbatim text transcription. For
   any quotation, citation, or evidentiary use, verify against the
   source page (the side-by-side viewer makes this one click).

---

## 8. Versioning

| Version | Date | Notes |
|---|---|---|
| v0.1 | 2026-05-08 | initial release after Stage-3 + Stage-4 GPT-mini audit (515 pages) + per-page 200 DPI JPEG renders |

Future tranches will append rather than replace.

---

## 9. Reproducing

See [README.md § Reproducibility](./README.md#reproducibility). The
deterministic parts (download, extraction, audit) can be re-run from any
commit. The non-deterministic parts (VLM outputs themselves) will vary
between runs; the audit trail shows the exact run that produced this
release.

---

## 10. Contact / corrections

Found an error? File an issue. Patches welcome. Per CC0, you may also
fork and redistribute with corrections under any license you like.
