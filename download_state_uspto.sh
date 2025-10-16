#!/bin/bash
# download_state_uspto.sh
# Summarize USPTO data status by year using both:
#   - Download state files (.download_state_YEAR.txt)
#   - Actual XML presence
#   - Year distribution from Qdrant embeddings
# Usage: ./download_state_uspto.sh [DATA_DIR]

set -euo pipefail

# --- Resolve data dir ---
DATA_DIR_INPUT="${1:-}"
if [ -n "$DATA_DIR_INPUT" ]; then
  DATA_DIR="$DATA_DIR_INPUT"
elif [ -n "${DATA_DIR:-}" ]; then
  : # use env DATA_DIR
elif [ -d "/mnt/storage_pool/uspto" ]; then
  DATA_DIR="/mnt/storage_pool/uspto"
else
  echo "❌ Could not resolve data directory."
  echo "   Provide it explicitly: ./download_state_uspto.sh /path/to/uspto-data"
  exit 1
fi

if [ ! -d "$DATA_DIR" ]; then
  echo "❌ Data directory does not exist: $DATA_DIR"
  exit 1
fi

echo "📂 Scanning: $DATA_DIR"
echo "======================================================"

# --- Show download state file progress ---
echo "📜 Checking download state files..."
STATE_FILES=("$DATA_DIR"/.download_state_*.txt)
FOUND_STATE_FILES=false

for sf in "${STATE_FILES[@]}"; do
  if [ -f "$sf" ]; then
    FOUND_STATE_FILES=true
    YEAR=$(basename "$sf" | grep -oE '[0-9]{4}')
    COMPLETED=$(wc -l < "$sf" | tr -d ' ')
    echo "📅 $YEAR — $COMPLETED completed downloads (from state file)"
  fi
done

if [ "$FOUND_STATE_FILES" = false ]; then
  echo "ℹ️ No .download_state_*.txt files found under $DATA_DIR"
fi

echo
echo "📦 Checking XML file coverage (this may take a few minutes)..."

declare -A YEAR_COUNTS
file_count=0
processed_count=0

while IFS= read -r -d $'\0' f; do
  ((file_count++))
  
  # progress indicator
  if (( file_count % 2000 == 0 )); then
    echo -n "."
    if (( file_count % 80000 == 0 )); then echo; fi
  fi

  base="$(basename "$f")"
  y=""

  # Try multiple filename formats
  y=$( (echo "$base" | awk -F'-' '/^.*-[0-9]{8}/ { print substr($NF,1,4) }' | head -n1) || true )
  if [ -z "$y" ]; then
    y=$( (echo "$base" | awk '/^US(19|20)[0-9]{2}/ { print substr($0,3,4) }' | head -n1) || true )
  fi
  if [ -z "$y" ]; then
    y=$( (echo "$base" | awk 'match($0, /(19|20)[0-9]{2}/) { print substr($0, RSTART, RLENGTH) }' | head -n1) || true )
  fi

  if [[ -n "$y" && "$y" =~ ^(19|20)[0-9]{2}$ ]]; then
    : "${YEAR_COUNTS[$y]:=0}"
    (( YEAR_COUNTS[$y]++ ))
    ((processed_count++))
  fi
done < <(find "$DATA_DIR" -type f -iname "*.xml" -print0)

echo
echo "======================================================"
echo "📊 USPTO XMLs present (by inferred year)"
echo "======================================================"
if [ "$processed_count" -eq 0 ]; then
  echo "⚠️  No XML files found under $DATA_DIR"
else
  for y in $(printf "%s\n" "${!YEAR_COUNTS[@]}" | sort -n); do
    printf "📅 %s — %'d XML files\n" "$y" "${YEAR_COUNTS[$y]}"
  done
  echo "------------------------------------------------------"
  echo "Total files scanned: $file_count"
  echo "Total files with valid year: $processed_count"
fi

# ======================================================
# Qdrant integration: check vectorized data per year
# ======================================================
echo
echo "🔍 Checking Qdrant year distribution (if available)..."

if command -v python3 >/dev/null 2>&1; then
  python3 - <<'PY'
from qdrant_client import QdrantClient
from collections import Counter
import re, sys

try:
    client = QdrantClient(host="localhost", port=6333)
    coll = "uspto_patents"
    scroll, next_offset = client.scroll(collection_name=coll, limit=1000, with_payload=True)
except Exception as e:
    print(f"⚠️  Could not connect to Qdrant: {e}")
    sys.exit(0)

counter = Counter()
total = 0

while True:
    for p in scroll:
        date = p.payload.get("filingDate") or ""
        match = re.search(r"(19|20)\d{2}", date)
        if match:
            counter[match.group(0)] += 1
        total += 1
    if not next_offset:
        break
    scroll, next_offset = client.scroll(collection_name=coll, limit=1000, with_payload=True, offset=next_offset)

if total == 0:
    print("⚠️  No data found in Qdrant.")
else:
    print("======================================================")
    print("🧠 Qdrant vectorized patents (by filing year)")
    print("======================================================")
    for year, count in sorted(counter.items()):
        print(f"📅 {year}: {count:,}")
    print("------------------------------------------------------")
    print(f"Total patents vectorized: {total:,}")
except Exception as e:
    print(f"⚠️  Error during Qdrant check: {e}")
PY
else
  echo "⚠️  Python3 not found; skipping Qdrant check."
fi

echo
echo "✅ Scan complete."