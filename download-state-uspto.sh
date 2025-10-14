#!/bin/bash
# download_state_uspto.sh
# Summarize which USPTO years you have by scanning XML filenames (no state files required).
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

# --- Find XMLs and extract years from filenames ---
echo "📂 Scanning: $DATA_DIR (Progress will appear as dots...)"

declare -A YEAR_COUNTS
file_count=0
processed_count=0

while IFS= read -r -d $'\0' f; do
  ((file_count++))
  
  # Progress indicator that flushes every 1000 files
  if (( file_count % 1000 == 0 )); then
    echo -n "."
    # Add a newline every 80 dots (80,000 files) to keep lines from getting too long
    if (( file_count % 80000 == 0 )); then
        echo
    fi
  fi

  base="$(basename "$f")"
  y=""

  # ROBUSTNESS FIX: Wrap each pipeline in '(...) || true' to prevent set -e from exiting on failure
  y=$( (echo "$base" | awk -F'-' '/^.*-[0-9]{8}/ { print substr($NF,1,4) }' | head -n1) || true )

  if [ -z "$y" ]; then
    y=$( (echo "$base" | awk '/^US(19|20)[0-9]{2}/ { print substr($0,3,4) }' | head -n1) || true )
  fi

  if [ -z "$y" ]; then
    # ROBUSTNESS FIX: Replaced potentially failing 'grep -P' with a portable awk command
    y=$( (echo "$base" | awk 'match($0, /(19|20)[0-9]{2}/) { print substr($0, RSTART, RLENGTH) }' | head -n1) || true )
  fi

  if [[ -n "$y" && "$y" =~ ^(19|20)[0-9]{2}$ ]]; then
    : "${YEAR_COUNTS[$y]:=0}"
    (( YEAR_COUNTS[$y]++ ))
    ((processed_count++))
  fi
done < <(find "$DATA_DIR" -type f -iname "*.xml" -print0)

echo # Final newline after progress dots

if [ "$processed_count" -eq 0 ]; then
  if [ "$file_count" -gt 0 ]; then
    echo "ℹ️  Found $file_count XML files, but could not infer any years from filenames."
  else
    echo "ℹ️  No XML files found under $DATA_DIR"
  fi
  exit 0
fi

# --- Print summary sorted by year ---
echo "======================================================"
echo "📊 USPTO XMLs present (by inferred year)"
echo "Data directory: $DATA_DIR"
echo "======================================================"
for y in $(printf "%s\n" "${!YEAR_COUNTS[@]}" | sort -n); do
  printf "📅 %s — %'d files\n" "$y" "${YEAR_COUNTS[$y]}"
done
echo "======================================================"
echo "Total files scanned: $file_count"
echo "Total files with valid year: $processed_count"
