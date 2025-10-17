#!/bin/bash
# download_state_uspto.sh
# Summarize USPTO data status by year using download state files
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
  echo "ERROR: Could not resolve data directory."
  echo "   Provide it explicitly: ./download_state_uspto.sh /path/to/uspto-data"
  exit 1
fi

if [ ! -d "$DATA_DIR" ]; then
  echo "ERROR: Data directory does not exist: $DATA_DIR"
  exit 1
fi

echo "Scanning: $DATA_DIR"
echo "======================================================"
echo "Download Status by Year"
echo "======================================================"

STATE_FILES=("$DATA_DIR"/.download_state_*.txt)
FOUND_STATE_FILES=false

for sf in "${STATE_FILES[@]}"; do
  if [ -f "$sf" ]; then
    FOUND_STATE_FILES=true
    YEAR=$(basename "$sf" | grep -oE '[0-9]{4}')
    COMPLETED=$(wc -l < "$sf" | tr -d ' ')
    echo "$YEAR: $COMPLETED downloads completed"
  fi
done

if [ "$FOUND_STATE_FILES" = false ]; then
  echo "INFO: No .download_state_*.txt files found under $DATA_DIR"
fi

echo "======================================================"

# Check global download log
GLOBAL_LOG="/mnt/storage_pool/download_state/global_download_log.txt"
if [ -f "$GLOBAL_LOG" ]; then
  echo
  echo "Global Download Log:"
  echo "======================================================"
  cat "$GLOBAL_LOG"
  echo "======================================================"
fi

echo
echo "Scan complete."
