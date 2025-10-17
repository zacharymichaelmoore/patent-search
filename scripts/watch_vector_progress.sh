#!/bin/bash
# watch_vector_progress.sh
# Monitors Qdrant vectorization progress with ETA estimation based on download log

QDRANT_URL="http://localhost:6333/collections/uspto_patents"
VECTOR_LOG="/mnt/storage_pool/global/vectorization_log.csv"

if [ ! -s "$VECTOR_LOG" ]; then
  echo "⚠️ Vectorization log missing or empty at $VECTOR_LOG"
  echo "   Run scripts/download_data.sh first to populate the log."
  exit 1
fi

TOTAL=$(tail -n1 "$VECTOR_LOG" | awk -F',' '{print $5}')
TOTAL=${TOTAL:-0}
if ! [[ "$TOTAL" =~ ^[0-9]+$ ]]; then
  echo "⚠️ Could not parse total count from $VECTOR_LOG (value: $TOTAL)"
  exit 1
fi

echo "📊 Monitoring Qdrant indexing progress..."
echo "Target: $TOTAL total patents"
echo "Polling every 60s... (Ctrl+C to stop)"
echo "---------------------------------------------------------"

last_count=0
last_time=$(date +%s)

while true; do
  now=$(date +%s)
  count=$(curl -s "$QDRANT_URL" | jq -r .result.points_count)

  if [[ "$count" =~ ^[0-9]+$ ]]; then
    diff=$((count - last_count))
    dt=$((now - last_time))
    rate=0
    if (( dt > 0 )); then
      rate=$(awk "BEGIN {printf \"%.1f\", $diff / $dt}")
    fi
    pct=$(awk "BEGIN {printf \"%.2f\", ($count / $TOTAL) * 100}")
    remaining=$((TOTAL - count))
    if (( remaining < 0 )); then
      remaining=0
    fi
    if (( $(echo "$rate > 0" | bc -l) )); then
      eta_sec=$(awk "BEGIN {printf \"%.0f\", $remaining / $rate}")
      eta_min=$((eta_sec / 60))
      printf "🧠 %'d indexed (%.2f%%) | +%d in last %ds | ETA: ~%d min\n" \
        "$count" "$pct" "$diff" "$dt" "$eta_min"
    else
      printf "🧠 %'d indexed (%.2f%%) | waiting for next batch...\n" "$count" "$pct"
    fi
    last_count=$count
    last_time=$now
  else
    echo "⚠️ Could not retrieve count (Qdrant not responding?)"
  fi

  sleep 60
done
