#!/usr/bin/env bash
# Download UAP/PURSUE Release 01 videos via DVIDS public pages
set -e
ROOT="$(dirname "$0")/.."
OUT="$ROOT/release_1_pdfs/videos"
mkdir -p "$OUT"
LOG="$OUT/_videos.log"
: > "$LOG"

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36'
DVIDS_IDS="1006056 1006059 1006060 1006062 1006063 1006067 1006073 1006074 1006076 1006078 1006079 1006080 1006082 1006083 1006087 1006088 1006089 1006093 1006094 1006097 1006104 1006105 1006106 1006107 1006110 1006111 1006119 1006159"

for id in $DVIDS_IDS; do
  # Fetch DVIDS page
  page=$(mktemp)
  curl -sL -A "$UA" -o "$page" "https://www.dvidshub.net/video/${id}"
  # Extract MP4 URL (highest quality, prefer cloudfront direct)
  mp4_url=$(grep -oE 'https://[^"]*\.(mp4|mov)[^"]*' "$page" | head -1)
  title_slug=$(grep -oE "href=\"/video/${id}/[^\"]+\"" "$page" | head -1 | sed -E 's|href="/video/[0-9]+/||; s|"$||')
  if [ -z "$title_slug" ]; then title_slug="${id}"; fi
  out="$OUT/${title_slug}.mp4"

  if [ -z "$mp4_url" ]; then
    echo "FAIL ${id} (no mp4 url found)" | tee -a "$LOG"
    rm -f "$page"
    continue
  fi

  if [ -s "$out" ] && [ "$(stat -c %s "$out")" -gt 1000 ]; then
    echo "SKIP $id $title_slug (exists)" | tee -a "$LOG"
    rm -f "$page"
    continue
  fi

  curl -sL -A "$UA" -o "$out" "$mp4_url"
  size=$(stat -c %s "$out" 2>/dev/null || echo 0)
  ftype=$(file -b "$out" | cut -d, -f1)
  if [ "$size" -gt 10000 ]; then
    echo "OK $id $size $title_slug ($ftype)" | tee -a "$LOG"
  else
    echo "FAIL $id $size $title_slug" | tee -a "$LOG"
    rm -f "$out"
  fi
  rm -f "$page"
done

echo ""
echo "=== Summary ==="
echo "Total videos: $(ls "$OUT"/*.mp4 2>/dev/null | wc -l)"
echo "Total size: $(du -sh "$OUT" 2>/dev/null | cut -f1)"
