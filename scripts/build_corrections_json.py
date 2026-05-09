#!/usr/bin/env python3
"""Build corrections.json from web/data.json.

Each correction record is one of three kinds:
  - location_fix: source CSV had a wrong location label
  - date_fix: source CSV had a wrong date
  - year_inferred: source CSV said N/A for date, we inferred year from filename

Output is a stable, hand-auditable JSON file that documents every
manual or programmatic correction applied to PURSUE Release 01 metadata.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "web" / "data.json"
OUT = ROOT / "corrections.json"


def main():
    data = json.loads(DATA.read_text())
    events = data["events"]

    corrections = []
    for ev in events:
        if ev.get("location_fixed"):
            corrections.append({
                "kind": "location_fix",
                "record_title": ev["title"],
                "source_field": "Incident Location",
                "corrected_to": ev.get("location_name"),
                "reason": "CSV title↔location mismatch caught in spot-check",
            })
        if ev.get("date_fixed"):
            corrections.append({
                "kind": "date_fix",
                "record_title": ev["title"],
                "source_field": "Incident Date",
                "corrected_to": ev.get("date_iso"),
                "label": ev.get("date_label"),
                "reason": "CSV year disagreed with PDF header / filename",
            })
        if ev.get("year_inferred") and not ev.get("date_fixed"):
            corrections.append({
                "kind": "year_inferred",
                "record_title": ev["title"],
                "source_field": "Incident Date",
                "source_value": ev.get("date_raw"),
                "inferred_year": ev.get("year"),
                "label": ev.get("date_label"),
                "reason": "CSV said N/A; year recovered from filename pattern",
            })

    output = {
        "schema_version": 1,
        "release": "PURSUE Release 01",
        "release_date": "2026-05-08",
        "total_records": len(events),
        "corrections_count": len(corrections),
        "corrections_breakdown": {
            "location_fix": sum(1 for c in corrections if c["kind"] == "location_fix"),
            "date_fix": sum(1 for c in corrections if c["kind"] == "date_fix"),
            "year_inferred": sum(1 for c in corrections if c["kind"] == "year_inferred"),
        },
        "corrections": corrections,
    }
    OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Wrote {OUT}")
    print(f"  total corrections: {len(corrections)}")
    for k, v in output["corrections_breakdown"].items():
        print(f"    {k}: {v}")


if __name__ == "__main__":
    main()
