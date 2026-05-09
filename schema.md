# Schema

The dataset ships in two parallel forms with identical per-record
fields. They differ only in how the page image is delivered.

| Form | File(s) | HF config | How `image` is delivered |
|---|---|---|---|
| **JSONL** | `corpus.jsonl` (14 MB) | `text` (default) | Path string in `page_image_path` field |
| **Parquet shards** | `pages-*.parquet` (5 × ~400 MB) | `pages` | Inline JPEG bytes in `image` column, decoded as PIL.Image |

`corpus.jsonl` is one JSON object per line, one line per page, built
by `scripts/build_corpus_jsonl.py` from `mimo_processed/` plus the
cleaned metadata in `web/data.json`. The parquet shards are then built
from `corpus.jsonl` + `release_1_renders/*.jpg` by
`scripts/build_parquet_shards.py`.

## Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `record_id` | string | yes | Stable cross-page identifier for the source record. Format: `{pdf_stem}` |
| `pdf_stem` | string | yes | Base filename without extension. Maps 1:1 to a directory under `mimo_processed/` |
| `page_num` | integer | yes | 1-indexed page number within the PDF |
| `total_pages` | integer | yes | Total pages in the source PDF (from `_meta.json`) |
| `text` | string | yes | Full Markdown content of the page, including `*Image: ...*` tags |
| `text_chars` | integer | yes | Length of `text` in characters |
| `image_tags` | array[string] | yes | Extracted `*Image:* ...` content (the inside of each tag), in document order |
| `image_tag_source` | string | yes | Either `mimo-v2.5` (original VLM) or `gpt-5.4-mini-2026` (re-described in audit) |
| `image_tag_audit_score` | integer\|null | yes (nullable) | Always present. The mimo-judge consistency score (0-3) that triggered re-description, or `null` when the page kept its original mimo-v2.5 description. |
| `image_tag_audit_categories` | array[string]\|null | yes (nullable) | Always present. Strict-extract categories from the audit pass, or `null` when not re-described. |
| `source_url` | string | yes | Direct download URL on war.gov |
| `sha256` | string | yes | sha256 of the source PDF / IMG file |
| `file_size_bytes` | integer | yes | Source file size |
| `agency` | string | yes | Originating agency. Values present in v0.1: `Department of War`, `Department of State`, `FBI`, `NASA`. |
| `record_type` | string | yes | One of: `mission_report`, `cable`, `case_file`, `photo`, `imagery`, `report`, `summary`, `transcript`, `other` |
| `title` | string | yes | Cleaned record title |
| `incident_location` | string\|null | no | Cleaned location label, may be null when not applicable |
| `incident_location_corrected` | bool | yes | True if we corrected the source CSV location for this record |
| `incident_date_iso` | string\|null | no | YYYY-MM-DD if known. Null for `N/A` dates that we could not infer |
| `year` | integer\|null | no | Year extracted from `incident_date_iso` or inferred from filename |
| `year_inferred` | bool | yes | True if `year` came from filename pattern, not the CSV date column |
| `incident_date_corrected` | bool | yes | True if we corrected the CSV date for this record |
| `description_blurb` | string | no | Source CSV description text |
| `dvids_video_id` | string | no | DVIDS video ID if this record has a paired video |
| `vlm_model` | string | yes | VLM that produced the text |
| `vlm_prompt_version` | string | yes | Prompt version label (e.g. `v3.1-uap-archive`) |
| `vlm_dpi` | integer | yes | DPI used to render the page before VLM ingestion |
| `extraction_completed_at` | string | yes | ISO timestamp of the extraction run |
| `page_image_path` | string\|null | yes (nullable) | Repo-relative path to the rendered page image, e.g. `release_1_renders/<stem>/page_NNN.jpg`. Null for pages whose source has not been re-rendered. Standalone image records (`fbi-photo-*.png`, NASA Apollo `*.jpg`) keep their native format under `page_001.<ext>`. |
| `page_image_format` | string\|null | yes (nullable) | `jpeg` for VLM-rendered PDF pages, `png` or `jpeg` for native standalone image records. |
| `render_dpi` | integer\|null | yes (nullable) | DPI used to render this page image. `200` for VLM-rendered pages; `null` for native standalone images. |
| `render_max_dim` | integer\|null | yes (nullable) | Max dimension cap (px) applied during render. `2000` for the v1 release. |
| `render_jpeg_quality` | integer\|null | yes (nullable) | JPEG encoder quality used. `88` for v1; `null` for native PNG records. |
| `render_version` | string\|null | yes (nullable) | Render parameter version label, e.g. `v1-200dpi-cap2000-jpeg88`. Bump when render parameters change so downstream caches can invalidate. |

## Example

```json
{
  "record_id": "65_hs1-834228961_62-hq-83894_section_4",
  "pdf_stem": "65_hs1-834228961_62-hq-83894_section_4",
  "page_num": 191,
  "total_pages": 232,
  "text": "## UNCLASSIFIED\n\n*Image: A clipped newspaper article titled “These Flying Discs Are at It Again, Virginians Report” mounted on a beige document page...*\n\n...",
  "text_chars": 4280,
  "image_tags": [
    "A clipped newspaper article titled “These Flying Discs Are at It Again, Virginians Report” ..."
  ],
  "image_tag_source": "gpt-5.4-mini-2026",
  "image_tag_audit_score": 1,
  "image_tag_audit_categories": ["newspaper_clipping_illustration"],
  "source_url": "https://www.war.gov/medialink/ufo/release_1/65_HS1-834228961_62-HQ-83894_Section_4.pdf",
  "sha256": "abc123...",
  "file_size_bytes": 21458912,
  "agency": "FBI",
  "record_type": "case_file",
  "title": "FBI 62-HQ-83894 Section 4",
  "incident_location": "Virginia, USA",
  "incident_location_corrected": false,
  "incident_date_iso": "1949-05-13",
  "year": 1949,
  "year_inferred": false,
  "incident_date_corrected": false,
  "vlm_model": "mimo-v2.5",
  "vlm_prompt_version": "v3.1-uap-archive",
  "vlm_dpi": 200,
  "extraction_completed_at": "2026-05-08T15:37:46",
  "page_image_path": "release_1_renders/65_hs1-834228961_62-hq-83894_section_4/page_191.jpg",
  "page_image_format": "jpeg",
  "render_dpi": 200,
  "render_max_dim": 2000,
  "render_jpeg_quality": 88,
  "render_version": "v1-200dpi-cap2000-jpeg88"
}
```

## Notes

- `text` retains Markdown formatting (headings, tables, bold, image
  tags). For pure-text usage, strip with any Markdown library.
- `image_tags` is denormalized for convenience; the same content also
  appears in `text` between `*Image:` and `*` markers.
- Records have a many-to-one relation between page and source file. To
  reconstruct a single source PDF, group by `pdf_stem` and sort by
  `page_num`.
- The `pages` parquet config replaces `page_image_path` with an
  inline `image` column (`datasets.Image()`). Loaders return PIL.Image
  directly — no `cast_column` needed:
  ```python
  ds = load_dataset("alex-zhang42/ufo-pursue-open-atlas", "pages", split="train")
  ds[0]["image"]  # PIL.Image
  ```
