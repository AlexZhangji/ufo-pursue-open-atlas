#!/usr/bin/env python3
"""Parse uap-csv.csv into a clean events.json for the globe visualization.
Also scans local release_1_pdfs/ for downloaded PDFs and videos.
"""
import csv
import json
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "uap-csv.csv"
OUT_PATH = ROOT / "web" / "data.json"
PDF_DIR = ROOT / "release_1_pdfs"
VIDEO_DIR = PDF_DIR / "videos"

# Curated geocoding for incident locations.
GEOCODE = {
    "Moon": {"lat": None, "lng": None, "off_earth": "moon"},
    "Low Earth Orbit": {"lat": None, "lng": None, "off_earth": "leo"},
    "Persian Gulf": {"lat": 26.5, "lng": 51.5},
    "Arabian Gulf": {"lat": 25.0, "lng": 52.0},
    "Strait of Hormuz": {"lat": 26.5, "lng": 56.4},
    "Mediterranean Sea": {"lat": 35.0, "lng": 18.0},
    "Aegean Sea": {"lat": 38.5, "lng": 25.0},
    "Arabian Sea": {"lat": 14.0, "lng": 65.0},
    "Gulf of Oman": {"lat": 24.5, "lng": 58.5},
    "Gulf of Aden": {"lat": 12.5, "lng": 47.0},
    "Iraq": {"lat": 33.0, "lng": 44.0},
    "Iran": {"lat": 32.0, "lng": 53.0},
    "Syria": {"lat": 35.0, "lng": 38.0},
    "United Arab Emirates": {"lat": 24.0, "lng": 54.0},
    "UAE": {"lat": 24.0, "lng": 54.0},
    "Greece": {"lat": 39.0, "lng": 22.0},
    "Middle East": {"lat": 28.0, "lng": 50.0},
    "Turkey": {"lat": 39.0, "lng": 35.0},
    "Japan": {"lat": 36.0, "lng": 138.0},
    "East China Sea": {"lat": 30.0, "lng": 125.0},
    "Indo-PACOM": {"lat": 20.0, "lng": 140.0},
    "INDOPACOM": {"lat": 20.0, "lng": 140.0},
    "Pacific Ocean": {"lat": 0.0, "lng": -160.0},
    "Pacific Time Zone": {"lat": 38.0, "lng": -120.0},
    "Germany": {"lat": 51.0, "lng": 10.0},
    "Netherlands": {"lat": 52.0, "lng": 5.0},
    "Azerbaijan": {"lat": 40.0, "lng": 47.0},
    "Georgia": {"lat": 42.0, "lng": 43.5},
    "Tbilisi, Georgia": {"lat": 41.72, "lng": 44.78},
    "Kazakhstan": {"lat": 48.0, "lng": 67.0},
    "Turkmenistan": {"lat": 38.0, "lng": 60.0},
    "Ashgabat, Turkmenistan": {"lat": 37.95, "lng": 58.38},
    "Africa": {"lat": 8.0, "lng": 30.0},
    "Djibouti": {"lat": 11.5, "lng": 43.0},
    "AFRICOM": {"lat": 8.0, "lng": 30.0},
    "United States": {"lat": 39.0, "lng": -98.0},
    "Western United States": {"lat": 39.0, "lng": -111.0},
    "Southern United States": {"lat": 32.0, "lng": -97.0},
    "North America": {"lat": 39.0, "lng": -100.0},
    "Detroit, MI": {"lat": 42.33, "lng": -83.05},
    "Mexico": {"lat": 23.0, "lng": -102.0},
    "Papua New Guinea": {"lat": -6.0, "lng": 145.0},
    "Port Moresby, Papua New Guinea": {"lat": -9.45, "lng": 147.18},
}

AGENCY_COLORS = {
    "Department of War": "#E8A861",
    "FBI": "#7AB8D9",
    "NASA": "#79D9C3",
    "Department of State": "#D4A8A8",
}


def parse_date(s: str):
    s = (s or "").strip()
    if not s or s == "N/A":
        return None, None, ""
    label = s
    if "-" in s and not s.startswith("Late"):
        s = s.split("-")[0].strip()
    if re.match(r"^Late \d{4}$", s):
        year = int(re.search(r"\d{4}", s).group(0))
        return f"{year}-12-15", year, label
    m = re.match(r"^(\d{4})$", s)
    if m:
        year = int(m.group(1))
        return f"{year}-06-15", year, label
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            d = datetime.strptime(s, fmt)
            return d.strftime("%Y-%m-%d"), d.year, label
        except ValueError:
            continue
    return None, None, label


def infer_year_from_filename(url_or_title: str) -> tuple[int | None, str]:
    """Extract approximate year from a filename or title when CSV gives N/A.
    Returns (year, label_hint).
    """
    s = (url_or_title or "").lower()
    # Explicit year ranges first
    m = re.search(r"_(\d{4})[-_](\d{4})_", s) or re.search(r"_(\d{4})-(\d{4})", s)
    if m:
        y0, y1 = int(m.group(1)), int(m.group(2))
        return (y0 + y1) // 2, f"~{y0}–{y1} (filename)"
    # Range like 1946-7
    m = re.search(r"(\d{4})-(\d)_", s)
    if m and int(m.group(2)) < 10:
        y0 = int(m.group(1))
        return y0, f"~{y0}–{(y0 // 10) * 10 + int(m.group(2))} (filename)"
    # Single year in path
    for m in re.finditer(r"\b(19[3-9]\d|19[2-7]\d|20[0-2]\d)\b", s):
        y = int(m.group(0))
        if 1925 <= y <= 2030:
            return y, f"~{y} (filename)"
    # Specific case file numbers known to span 1947-1968
    if "62-hq-83894" in s:
        return 1957, "~1947–1968 (FBI 62-HQ-83894 case file)"
    if "100-de-26505" in s:
        return 1957, "~1957 (FBI 100-DE-26505)"
    if "100-de-18221" in s:
        return 1958, "~1958 (FBI 100-DE-18221)"
    if "incident_summaries" in s:
        return 1955, "~1952–1969 (Project Blue Book era)"
    if "059uap" in s:
        return 1955, "~1947–1969 (USAF UFO archives)"
    if "ufo's_and_defense" in s or "ufos_and_defense" in s:
        return 1965, "~1960s (CIA/USAF analytical paper)"
    return None, ""


def find_local_pdf(url: str) -> str | None:
    """Map war.gov URL to local downloaded path (relative to articles/uap-files/)."""
    if not url or "war.gov" not in url:
        return None
    fname = Path(urlparse(url).path).name
    # Try lowercase
    candidates = [fname, fname.lower()]
    for c in candidates:
        path = PDF_DIR / c
        if path.exists():
            return f"release_1_pdfs/{c}"
    return None


def find_local_video(dvids_id: str) -> str | None:
    """Map DVIDS ID to local downloaded mp4 path."""
    if not dvids_id or not dvids_id.isdigit():
        return None
    if not VIDEO_DIR.exists():
        return None
    for path in VIDEO_DIR.glob(f"*dvids{dvids_id}.mp4"):
        return f"release_1_pdfs/videos/{path.name}"
    return None


def jitter_for(idx: int, total_at_loc: int) -> tuple[float, float]:
    """Deterministic jitter for events sharing the same coordinate.
    Sunflower disc spread (golden angle) with radius scaled to cluster size.
    Big clusters (24+) spread up to ~9 degrees so they fan out visibly.
    """
    if total_at_loc <= 1:
        return 0.0, 0.0
    import math
    angle = (idx * 137.5077) % 360  # golden angle
    # Stronger spread: small clusters 1-2°, big clusters up to ~9°
    max_radius = min(9.0, 1.0 + math.sqrt(total_at_loc) * 1.6)
    actual_radius = max_radius * math.sqrt((idx + 0.5) / total_at_loc)
    dlat = actual_radius * math.cos(math.radians(angle))
    dlng = actual_radius * math.sin(math.radians(angle))
    return dlat, dlng


# Manual metadata corrections — source war.gov CSV has title↔location mismatches
# we caught in spot-checks. Each entry: title-substring → corrected location.
# Recorded so they're traceable + reversible.
LOCATION_FIXES = {
    "DOW-UAP-D5, Mission Report, Arabian Gulf": "Arabian Gulf",   # CSV had "Mediterranean Sea"
    "DOW-UAP-D6, Mission Report, Arabian Gulf": "Arabian Gulf",   # CSV had "Pacific Ocean"
    "DOW-UAP-D8, Mission Report, Djibouti":     "Djibouti",       # CSV had "Mediterranean Sea"
    "DOW-UAP-D42, Range Fouler Debrief, Japan": "Japan",          # CSV had "Arabian Gulf"
}
# Date corrections — CSV got year wrong on Mexico cable (2003 vs 2023 in PDF header)
DATE_FIXES = {
    "State Department UAP Cable 5, Mexico, September 16, 2003": ("9/16/2023", "Sep 16, 2023 (corrected from CSV's 2003)"),
}


def main():
    rows = []
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            title = row.get("Title", "").strip().replace("\n", " ")
            if not title:
                continue
            agency = row.get("Agency", "").strip()
            type_ = row.get("Type", "").strip()
            iloc = row.get("Incident Location", "").strip()
            idate_raw = row.get("Incident Date", "").strip()
            desc = row.get("Description Blurb", "").strip().replace("\n", " ")
            url = row.get("PDF | Image Link", "").strip()
            dvids = row.get("DVIDS Video ID", "").strip()
            thumb = row.get("Modal Image", "").strip()
            video_pair = row.get("Video Pairing", "").strip()
            pdf_pair = row.get("PDF Pairing", "").strip()

            # Apply manual fixes for known source-data errors
            location_fixed = False
            for prefix, fixed_loc in LOCATION_FIXES.items():
                if title.startswith(prefix):
                    iloc = fixed_loc
                    location_fixed = True
                    break
            date_fixed = False
            if title in DATE_FIXES:
                idate_raw, fix_label = DATE_FIXES[title]
                date_fixed = True

            iso, year, dlabel = parse_date(idate_raw)
            if date_fixed:
                dlabel = fix_label
            year_inferred = False
            if year is None:
                inferred_year, inferred_label = infer_year_from_filename(url + " " + title)
                if inferred_year:
                    year = inferred_year
                    iso = f"{inferred_year}-06-15"
                    dlabel = inferred_label
                    year_inferred = True

            geo = GEOCODE.get(iloc, None)
            if geo is None and iloc and iloc != "N/A":
                for k, v in GEOCODE.items():
                    if k.lower() in iloc.lower() or iloc.lower() in k.lower():
                        geo = v
                        break

            local_pdf = find_local_pdf(url)
            local_vid = find_local_video(dvids)

            rec = {
                "id": i,
                "title": title,
                "type": type_,
                "agency": agency,
                "agency_color": AGENCY_COLORS.get(agency, "#888"),
                "date_raw": idate_raw,
                "date_label": dlabel,
                "date_iso": iso,
                "year": year,
                "year_inferred": year_inferred,
                "location_fixed": location_fixed,
                "date_fixed": date_fixed,
                "location_name": iloc,
                "cluster_key": iloc,  # used for grouping at click
                "lat_base": geo["lat"] if geo else None,
                "lng_base": geo["lng"] if geo else None,
                "lat": geo["lat"] if geo else None,
                "lng": geo["lng"] if geo else None,
                "off_earth": (geo or {}).get("off_earth", None),
                "description": desc,
                "pdf_url": url if url and not url.startswith("https://www.dvidshub") else "",
                "dvids_id": dvids,
                "video_url": f"https://www.dvidshub.net/video/{dvids}" if dvids and dvids.isdigit() else "",
                "video_embed": f"https://www.dvidshub.net/video/{dvids}/embed" if dvids and dvids.isdigit() else "",
                "thumbnail": thumb,
                "video_pairing": video_pair,
                "pdf_pairing": pdf_pair,
            }
            rows.append(rec)

    # Apply deterministic jitter to events sharing the same coordinate
    from collections import defaultdict
    coord_groups = defaultdict(list)
    for r in rows:
        if r["lat_base"] is not None and r["lng_base"] is not None:
            key = (round(r["lat_base"], 3), round(r["lng_base"], 3))
            coord_groups[key].append(r)
    for key, group in coord_groups.items():
        if len(group) > 1:
            for idx, r in enumerate(group):
                dlat, dlng = jitter_for(idx, len(group))
                r["lat"] = r["lat_base"] + dlat
                r["lng"] = r["lng_base"] + dlng

    n_geo = sum(1 for r in rows if r["lat"] is not None or r["off_earth"])
    n_year = sum(1 for r in rows if r["year"])
    n_year_inferred = sum(1 for r in rows if r.get("year_inferred"))
    print(f"Total events: {len(rows)}")
    print(f"  Geocoded: {n_geo}")
    print(f"  Have year: {n_year} (of which inferred from filename: {n_year_inferred})")

    years = [r["year"] for r in rows if r["year"]]
    year_min, year_max = (min(years), max(years)) if years else (1948, 2026)

    from collections import Counter
    by_agency = Counter(r["agency"] for r in rows)

    out = {
        "events": rows,
        "stats": {
            "total": len(rows),
            "geocoded": n_geo,
            "with_year": n_year,
            "year_min": year_min,
            "year_max": year_max,
            "by_agency": dict(by_agency),
            "n_undated": sum(1 for r in rows if not r["year"]),
            "n_unlocated": sum(1 for r in rows if r["lat"] is None and not r["off_earth"]),
            "n_year_inferred": n_year_inferred,
        },
        "agency_colors": AGENCY_COLORS,
    }

    # Scrape DVIDS for direct mp4 URLs (idempotent — re-uses cached if available)
    import urllib.request, time
    cache_path = OUT_PATH.parent / "_dvids_mp4_cache.json"
    cache = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())
    UA = "Mozilla/5.0 Chrome/132"
    seen = {}
    n_scraped = 0
    for e in rows:
        did = e.get("dvids_id", "")
        if not did or not did.isdigit():
            continue
        if did in cache:
            e["video_mp4"] = cache[did]
            continue
        if did in seen:
            e["video_mp4"] = seen[did]
            continue
        url = f"https://www.dvidshub.net/video/{did}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                html = r.read().decode("utf-8", "ignore")
            m = re.search(r'https://[^"\']*\.cloudfront\.net/[^"\']*\.(?:mp4|mov)', html)
            mp4 = m.group(0) if m else ""
            seen[did] = mp4
            cache[did] = mp4
            e["video_mp4"] = mp4
            n_scraped += 1
            time.sleep(0.2)
        except Exception as ex:
            print(f"  DVIDS {did} err: {ex}")
            e["video_mp4"] = ""
    if n_scraped:
        cache_path.write_text(json.dumps(cache, indent=2))
        print(f"Scraped {n_scraped} new DVIDS mp4 URLs (cached at {cache_path.name})")

    OUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
