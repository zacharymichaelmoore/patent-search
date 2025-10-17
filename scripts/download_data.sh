#!/usr/bin/env bash
# Usage:
#   ./download-data.sh <JURISDICTION> <YEAR>
#
# Examples:
#   ./download-data.sh uspto 2024
#   ./download-data.sh epo 2023
#   ./download-data.sh cnipa 2022
#
# Arguments:
#   <JURISDICTION>   The data source (e.g., uspto, epo, cnipa)
#   <YEAR>           The year of data to download
#
# Notes:
#   - The script automatically handles per-jurisdiction directories.
#   - API key is loaded from environment or Google Secret Manager.
#   - Global download logs are written to /mnt/storage_pool/download_state/.

set -euo pipefail

# ============================================================================
# GLOBAL CONFIGURATION
# ============================================================================

GLOBAL_STATE_DIR="/mnt/storage_pool/download_state"
GLOBAL_LOG="$GLOBAL_STATE_DIR/global_download_log.txt"
mkdir -p "$GLOBAL_STATE_DIR"

GLOBAL_VECTOR_DIR="/mnt/storage_pool/global"
VECTOR_LOG="$GLOBAL_VECTOR_DIR/vectorization_log.csv"
VECTOR_LOG_LOCK="$GLOBAL_VECTOR_DIR/vectorization_log.lock"
mkdir -p "$GLOBAL_VECTOR_DIR"
touch "$VECTOR_LOG"
touch "$VECTOR_LOG_LOCK"

# Load last known total vector-ready XML count
if [ -s "$VECTOR_LOG" ]; then
    LAST_VECTOR_TOTAL=$(tail -n1 "$VECTOR_LOG" | awk -F',' '{print $5}')
else
    LAST_VECTOR_TOTAL=0
fi
LAST_VECTOR_TOTAL=${LAST_VECTOR_TOTAL:-0}
if ! [[ "$LAST_VECTOR_TOTAL" =~ ^[0-9]+$ ]]; then
    LAST_VECTOR_TOTAL=0
fi

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

record_global_state() {
    local year=$1
    local month=$2
    local source=$(echo "$JURISDICTION" | tr '[:lower:]' '[:upper:]')
    local entry="${year}-${month}   ${source}"
    
    if ! grep -Fxq "$entry" "$GLOBAL_LOG" 2>/dev/null; then
        echo "$entry" >> "$GLOBAL_LOG"
    fi
}

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

is_completed() {
    grep -Fxq "$1" "$STATE_FILE"
}

mark_completed() {
    echo "$1" >> "$STATE_FILE"
}

validate_tar() {
    local tarfile=$1
    
    if tar -tf "$tarfile" >/dev/null 2>&1; then
        return 0
    elif tar -tzf "$tarfile" >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

append_vector_log() {
    local year="$1"
    local filename="$2"
    local xml_count="$3"

    (
        flock -w 60 9 || exit 1

        local current_total=0
        if [ -s "$VECTOR_LOG" ]; then
            current_total=$(tail -n1 "$VECTOR_LOG" | awk -F',' '{print $5}')
            if ! [[ "$current_total" =~ ^[0-9]+$ ]]; then
                current_total=0
            fi
        fi

        local new_total=$((current_total + xml_count))
        local timestamp
        timestamp=$(date '+%Y-%m-%d %H:%M:%S')
        printf "%s,%s,%s,%d,%d\n" "$timestamp" "$year" "$filename" "$xml_count" "$new_total" >> "$VECTOR_LOG"
        printf "%s" "$new_total"
    ) 9>"$VECTOR_LOG_LOCK"
}

download_redbook_year() {
    log "Red Book mode enabled for $YEAR (pre-2010)"

    local html index_file
    html=$(curl -fsSL "https://www.google.com/googlebooks/uspto-patents-redbook.html") || {
        log "Error: Unable to retrieve Red Book index page."
        return 1
    }

    index_file=$(mktemp)
    printf "%s\n" "$html" \
        | tr '\r' '\n' \
        | grep -o "I${YEAR}[0-9]\{4\}\(-SUPP\)\?\.ZIP" \
        | sort -u > "$index_file"

    if [ ! -s "$index_file" ]; then
        log "No Red Book entries found for $YEAR."
        rm -f "$index_file"
        return 0
    fi

    declare -A RECORDED_MONTHS=()

    while read -r FILENAME; do
        [ -z "$FILENAME" ] && continue

        if is_completed "$FILENAME"; then
            log "Skip: $FILENAME (already completed)"
            continue
        fi

        local month="${FILENAME:5:2}"
        if [ -z "${RECORDED_MONTHS[$month]+x}" ]; then
            RECORDED_MONTHS[$month]=1
            record_global_state "$YEAR" "$month"
            log "Recorded global state for $YEAR-$month"
        fi

        local TARGET_DIR="$DATA_DIR/${FILENAME%.ZIP}"
        if [ -d "$TARGET_DIR" ] && find "$TARGET_DIR" -maxdepth 1 -name "*.xml" -print -quit | grep -q .; then
            log "Skip: $FILENAME (folder '$TARGET_DIR' already contains XML files)"
            mark_completed "$FILENAME"
            continue
        fi

        log "Processing: $FILENAME (Red Book)"
        local TEMP_ARCHIVE="$DATA_DIR/${FILENAME}.tmp"
        local FINAL_ARCHIVE="$DATA_DIR/$FILENAME"
        local URL="http://storage.googleapis.com/patents/redbook/grants/$YEAR/$FILENAME"

        if curl -fsSL -o "$TEMP_ARCHIVE" "$URL"; then
            mv "$TEMP_ARCHIVE" "$FINAL_ARCHIVE"
        else
            log "Failed to download $FILENAME from $URL"
            rm -f "$TEMP_ARCHIVE"
            continue
        fi

        mkdir -p "$TARGET_DIR"
        if unzip -oq "$FINAL_ARCHIVE" -d "$TARGET_DIR/"; then
            find "$TARGET_DIR" -type f ! -iname "*.xml" -delete
            find "$TARGET_DIR" -type d -empty -delete
        else
            log "Extraction failed for $FILENAME. Cleaning up."
            rm -rf "$TARGET_DIR"
            rm -f "$FINAL_ARCHIVE"
            continue
        fi

        rm -f "$FINAL_ARCHIVE"

        local XML_COUNT
        XML_COUNT=$(find "$TARGET_DIR" -type f -iname "*.xml" | wc -l | tr -d ' ')
        XML_COUNT=${XML_COUNT:-0}
        if ! [[ "$XML_COUNT" =~ ^[0-9]+$ ]]; then
            XML_COUNT=0
        fi

        if NEW_TOTAL=$(append_vector_log "$YEAR" "$FILENAME" "$XML_COUNT"); then
            LAST_VECTOR_TOTAL=$NEW_TOTAL
            log "Vectorization log updated: +$XML_COUNT files (total $LAST_VECTOR_TOTAL)"
        else
            log "WARNING: Could not update vectorization log for $FILENAME (added $XML_COUNT)"
        fi

        mark_completed "$FILENAME"
        log "Completed: $FILENAME"
    done < "$index_file"

    rm -f "$index_file"
}

# ============================================================================
# ARGUMENT VALIDATION
# ============================================================================

if [ -z "${1:-}" ] || [ -z "${2:-}" ]; then
    echo "Usage: $0 <JURISDICTION> <YEAR>"
    echo "Example: $0 uspto 2024"
    exit 1
fi

JURISDICTION=$(echo "$1" | tr '[:upper:]' '[:lower:]')
YEAR=$2

# ============================================================================
# USPTO API KEY SETUP
# ============================================================================

if [ -z "${USPTO_API_KEY:-}" ]; then
    echo "[INFO] USPTO_API_KEY not found in environment. Loading from Google Secret Manager..."
    
    if command -v gcloud >/dev/null 2>&1; then
        USPTO_API_KEY=$(gcloud secrets versions access latest --secret="USPTO_API_KEY" 2>/dev/null)
        
        if [ -z "$USPTO_API_KEY" ]; then
            echo "Error: Could not fetch USPTO_API_KEY from Secret Manager."
            exit 1
        else
            echo "[INFO] USPTO_API_KEY loaded from Secret Manager."
        fi
    else
        echo "Error: gcloud not found and USPTO_API_KEY not set."
        exit 1
    fi
else
    echo "[INFO] USPTO_API_KEY found in environment."
fi

# ============================================================================
# DIRECTORY AND STATE SETUP
# ============================================================================

DATA_DIR="/mnt/storage_pool/${JURISDICTION}"
mkdir -p "$DATA_DIR"

STATE_FILE="$DATA_DIR/.download_state_$YEAR.txt"
LOG_FILE="$DATA_DIR/download_$YEAR.log"
touch "$STATE_FILE"

# ============================================================================
# START DOWNLOAD PROCESS
# ============================================================================

log "======================================================"
log "Starting ${JURISDICTION^^} data download for year: $YEAR"
log "State file: $STATE_FILE"
log "======================================================"

if [ -s "$STATE_FILE" ]; then
    COMPLETED_COUNT=$(wc -l < "$STATE_FILE")
    log "Resuming from state file with $COMPLETED_COUNT completed downloads"
fi

# ============================================================================
# MAIN DOWNLOAD LOOP
# ============================================================================

if [ "$YEAR" -lt 2010 ]; then
    download_redbook_year
else
    for MONTH in {1..12}; do
        MONTH_FORMATTED=$(printf "%02d" $MONTH)
        START_DATE="$YEAR-$MONTH_FORMATTED-01"
        END_DATE=$(date -d "$START_DATE +1 month -1 day" +%Y-%m-%d 2>/dev/null || \
                   date -v +1m -v -1d -j -f "%Y-%m-%d" "$START_DATE" +%Y-%m-%d)

        log "======================================================"
        log "Fetching file list for: $YEAR-$MONTH_FORMATTED"
        log "Date range: $START_DATE to $END_DATE"
        log "======================================================"

        # Fetch file list from USPTO API
        API_RESPONSE=$(curl -s -X GET \
            "https://api.uspto.gov/api/v1/datasets/products/appdt?fileDataFromDate=$START_DATE&fileDataToDate=$END_DATE&includeFiles=true" \
            -H 'Accept: application/json' \
            -H "x-api-key: $USPTO_API_KEY")
        
        if [ -z "$API_RESPONSE" ]; then
            log "Error: Failed to fetch file list for $YEAR-$MONTH_FORMATTED"
            continue
        fi

        # ========================================================================
        # PROCESS FILES (keep only latest revision per week; keep SUPP)
        # ========================================================================
        
        echo "$API_RESPONSE" \
        | jq -r '.bulkDataProductBag[0].productFileBag.fileDataBag[]?
                 | select(.fileName | endswith(".tar"))
                 | "\(.fileName) \(.fileDownloadURI)"' \
        | awk '
            function print_best() {
                for (k in best) print best[k];
            }
            
            {
                fn=$1; uri=$2;

                # Pass SUPP archives through as-is (unique key per SUPP file)
                if (fn ~ /^I[0-9]{8}-SUPP.*\.tar$/) {
                    key="SUPP:" fn;
                    best[key]=fn " " uri;
                    next;
                }

                # Track highest _rN for the base week
                week=substr(fn,2,8);
                rev=0;
                
                if (fn ~ /_r[0-9]+\.tar$/) {
                    if (match(fn, /_r([0-9]+)\.tar$/)) {
                        rev=substr(fn, RSTART+2, RLENGTH-6)+0;
                    }
                }
                
                key="WEEK:" week;
                
                if (!(key in best) || rev > bestrev[key]) {
                    best[key]=fn " " uri;
                    bestrev[key]=rev;
                }
            }
            
            END {
                print_best();
            }
        ' \
        | while read -r FILENAME API_URI; do
            [ -z "$FILENAME" ] && continue

            # Skip if already completed
            if is_completed "$FILENAME"; then
                log "Skip: $FILENAME (already completed)"
                continue
            fi

            # Fast-skip if week folder already exists
            WEEKSTAMP=${FILENAME:1:8}  # I20240125_r1.tar -> 20240125
            
            # Determine the target directory for this patent release
            TARGET_DIR="$DATA_DIR/I$WEEKSTAMP"
            if [[ "$FILENAME" == *"SUPP"* ]]; then
                TARGET_DIR="$DATA_DIR/I${WEEKSTAMP}-SUPP"
            fi

            if [ -d "$TARGET_DIR" ] && find "$TARGET_DIR" -maxdepth 1 -name "*.xml" -print -quit | grep -q .; then
                log "Skip: $FILENAME (week folder '$TARGET_DIR' already contains XML files)"
                mark_completed "$FILENAME"
                continue
            fi

            log "Processing: $FILENAME"
            TEMP_TAR="$DATA_DIR/${FILENAME}.tmp"
            FINAL_TAR="$DATA_DIR/$FILENAME"

            # Rate limit
            sleep 2

            # Download file
            if curl -L -f -o "$TEMP_TAR" -X GET "$API_URI" -H "x-api-key: $USPTO_API_KEY"; then
                log "Download complete: $FILENAME"
            else
                ERR=$?
                if [ $ERR -eq 22 ]; then
                    log "HTTP error (possibly 429) for $FILENAME. Will retry later."
                    sleep 10
                else
                    log "Failed to download $FILENAME (curl error $ERR). Will retry later."
                fi
                rm -f "$TEMP_TAR"
                continue
            fi

            # Validate tar file
            log "Validating $FILENAME"
            if validate_tar "$TEMP_TAR"; then
                mv "$TEMP_TAR" "$FINAL_TAR"
            else
                log "Corrupt tar: $FILENAME. Will retry later."
                rm -f "$TEMP_TAR"
                continue
            fi

            # Create target directory for this specific release
            mkdir -p "$TARGET_DIR"
            log "Extracting $FILENAME to $TARGET_DIR (temporarily all files, then deleting non-XML)"
            
            # Extract all files into the specific target directory
            if tar -xf "$FINAL_TAR" -C "$TARGET_DIR/"; then
                log "Initial extraction successful: $FILENAME"

                # Extract nested .ZIP files (extract all, then delete non-XML)
                if command -v unzip >/dev/null 2>&1; then
                    log "Extracting nested .ZIP files (temporarily all files, then deleting non-XML)..."
                    # Find ZIP files within the just-extracted tar directory and unzip them in place
                    find "$TARGET_DIR" -type f -name "*.ZIP" -exec sh -c '
                        DIRNAME=$(dirname "{}")
                        unzip -o -d "$DIRNAME" "{}" # Unzip all contents
                        rm "{}" # Remove the original ZIP file
                    ' \;
                    log "Finished nested .ZIP processing."
                else
                    log "unzip not found; skipping nested .ZIP extraction."
                fi

                # --- CRITICAL NEW STEP: DELETE NON-XML FILES ---
                log "Deleting all non-XML files from $TARGET_DIR and its subdirectories..."
                # Find and delete files that do NOT end with .xml (case-insensitive)
                # -depth ensures subdirectories are empty before trying to delete them
                find "$TARGET_DIR" -type f ! -iname "*.xml" -delete
                # Also remove any empty directories that might have been created or left after deleting files
                find "$TARGET_DIR" -type d -empty -delete
                log "Finished deleting non-XML files."

            else
                log "Extraction failed for $FILENAME. Cleaning up $TARGET_DIR and trying again later."
                rm -rf "$TARGET_DIR" # Remove the potentially incomplete/corrupt directory
                rm -f "$FINAL_TAR"
                continue
            fi

            rm -f "$FINAL_TAR"

            XML_COUNT=$(find "$TARGET_DIR" -type f -iname "*.xml" | wc -l | tr -d ' ')
            XML_COUNT=${XML_COUNT:-0}
            if ! [[ "$XML_COUNT" =~ ^[0-9]+$ ]]; then
                XML_COUNT=0
            fi
            if NEW_TOTAL=$(append_vector_log "$YEAR" "$FILENAME" "$XML_COUNT"); then
                LAST_VECTOR_TOTAL=$NEW_TOTAL
                log "Vectorization log updated: +$XML_COUNT files (total $LAST_VECTOR_TOTAL)"
            else
                log "WARNING: Could not update vectorization log for $FILENAME (added $XML_COUNT)"
            fi

            mark_completed "$FILENAME"
            log "Completed: $FILENAME"
        done

        record_global_state "$YEAR" "$MONTH_FORMATTED"
        log "Recorded global state for $YEAR-$MONTH_FORMATTED"
    done
fi

# ============================================================================
# POST-PROCESSING
# ============================================================================

log "======================================================"
log "Renaming .XML files to .xml..."

RENAMED_COUNT=0

# Iterate through all XML files across all extracted subdirectories
find "$DATA_DIR" -type f -name "*.XML" | while read -r file; do
    NEW_NAME="${file%.XML}.xml"
    if [ ! -e "$NEW_NAME" ]; then
        mv -- "$file" "$NEW_NAME"
        ((RENAMED_COUNT++))
    fi
done

log "Renamed $RENAMED_COUNT files"

# ============================================================================
# COMPLETION
# ============================================================================

log "======================================================"
log "All data for $YEAR ($JURISDICTION) downloaded and prepared"
log "Total completed: $(wc -l < "$STATE_FILE")"
log "Data directory: $DATA_DIR"
log "======================================================"
