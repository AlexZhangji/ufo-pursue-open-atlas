#!/usr/bin/env bash
# Download all UAP/PURSUE Release 01 PDFs from war.gov
# Bypasses Akamai by using full browser Sec-Fetch headers
set -e

OUT="$(dirname "$0")/../release_1_pdfs"
mkdir -p "$OUT"
LOG="$OUT/_download.log"
: > "$LOG"

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36'

dl() {
  local url="$1"
  local fname=$(basename "$url")
  local out="$OUT/$fname"
  if [ -s "$out" ] && [ "$(stat -c %s "$out")" -gt 1000 ]; then
    echo "SKIP (exists) $fname" | tee -a "$LOG"
    return 0
  fi
  local code
  code=$(curl -sL -A "$UA" \
    -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8" \
    -H "Accept-Language: en-US,en;q=0.5" \
    -H "Accept-Encoding: gzip, deflate, br" \
    -H "DNT: 1" -H "Connection: keep-alive" -H "Upgrade-Insecure-Requests: 1" \
    -H "Sec-Fetch-Dest: document" -H "Sec-Fetch-Mode: navigate" -H "Sec-Fetch-Site: none" \
    -H "Sec-Fetch-User: ?1" -H "Referer: https://www.war.gov/UFO/" \
    --compressed -w "%{http_code}" -o "$out" "$url")
  local size
  size=$(stat -c %s "$out" 2>/dev/null || echo 0)
  if [ "$code" = "200" ] && [ "$size" -gt 1000 ]; then
    # confirm it's a real PDF
    if file "$out" | grep -q "PDF document"; then
      echo "OK $code $size $fname" | tee -a "$LOG"
    else
      echo "BAD-NOT-PDF $code $size $fname" | tee -a "$LOG"
      rm -f "$out"
    fi
  else
    echo "FAIL $code $size $fname" | tee -a "$LOG"
    rm -f "$out"
  fi
}

# === A. Known specific PDFs (from Google index + manual) ===
KNOWN_URLS=(
  "https://www.war.gov/medialink/ufo/release_1/western_us_event_slides_5.08.2026.pdf"
  "https://www.war.gov/medialink/ufo/release_1/dow-uap-d54-mission-report-mediterranean-sea-na.pdf"
  "https://www.war.gov/medialink/ufo/release_1/65_hs1-101634279_100-de-26505.pdf"
  "https://www.war.gov/medialink/ufo/release_1/18_6369445_general_1948_vol_1.pdf"
)
for u in "${KNOWN_URLS[@]}"; do dl "$u"; done

# === B. FBI files: 65_HS1-834228961_62-HQ-83894_Section_2..10 + Serial_130/153 ===
for s in 2 3 4 5 6 7 9 10; do
  dl "https://www.war.gov/medialink/ufo/release_1/65_HS1-834228961_62-HQ-83894_Section_${s}.pdf"
done
for s in 130 153; do
  dl "https://www.war.gov/medialink/ufo/release_1/65_HS1-834228961_62-HQ-83894_Serial_${s}.pdf"
done

# === C. MR-series: try common lowercase + uppercase patterns ===
# Common AARO file naming: MissionReport_MR-XX.pdf, RangeFoulerDebrief_MR-XX.pdf, Tearline_MR-XX.pdf,
#                          Briefing_MR-XX.pdf, HistoricalDocument_MR-XX.pdf, Image_MR-XX.pdf
# The actual war.gov path likely uses some pattern. Probe both casings + dow-uap-d format.

# pattern 1: <type>_mr-NN.pdf (lowercase, hyphen)
declare -A MR_TYPES=(
  ["MissionReport"]="02 03 04 05 06 07 08 10 12 14 16 18 19 20 23 25 27 28 32 33 35 36 60 61 62 63 64 65 74 75"
  ["RangeFoulerDebrief"]="38 42 44 56 57 58"
  ["Tearline"]="50 51 52 54"
  ["Briefing"]="55"
  ["HistoricalDocument"]="48 49"
  ["Image"]="47"
)
for type in "${!MR_TYPES[@]}"; do
  for n in ${MR_TYPES[$type]}; do
    nn=$(printf "%02d" "$n")
    # Try several casing patterns
    for path in \
      "${type}_MR-${nn}.pdf" \
      "${type,,}_mr-${nn}.pdf" \
      "${type}_MR-${n}.pdf" \
      "${type,,}_mr-${n}.pdf"; do
      url="https://www.war.gov/medialink/ufo/release_1/${path}"
      dl "$url"
      # if found one, skip rest of variants for this MR
      if [ -s "$OUT/$(basename $url)" ]; then break; fi
    done
  done
done

# === D. dow-uap-d series mission reports (we know D54 exists) ===
# Try D1 through D80 with various locations
LOCATIONS=("mediterranean-sea-na" "middle-east-na" "indopacom-na" "africa-na" "europe-na" "americas-na" "north-america-na" "south-america-na" "central-command-na" "indo-pacific-na" "africa-command-na")
for n in $(seq 1 80); do
  for loc in "${LOCATIONS[@]}"; do
    nn=$(printf "%02d" "$n")
    for fname in "dow-uap-d${n}-mission-report-${loc}.pdf" "dow-uap-d${nn}-mission-report-${loc}.pdf"; do
      url="https://www.war.gov/medialink/ufo/release_1/${fname}"
      dl "$url"
      if [ -s "$OUT/$fname" ]; then break 2; fi
    done
  done
done

# === E. PR-series (often video, but also have PDF descriptors) ===
for n in $(seq 11 49); do
  nn=$(printf "%03d" "$n")
  url="https://www.war.gov/medialink/ufo/release_1/dow-uap-pr${nn}.pdf"
  dl "$url"
done

echo ""
echo "=== Summary ==="
echo "Total PDFs in $OUT: $(ls "$OUT"/*.pdf 2>/dev/null | wc -l)"
echo "See $LOG for full results"
