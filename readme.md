# Patent Search VM Setup

This document outlines the directory structure and data workflow for the patent search engine. The system is designed to download patent data, process it into vector embeddings, and serve it via a search API.

---

## Directory Structure

### `~/patent-search/` (Production Service)
- **Purpose**: The main patent search API service.
- **Port**: `8090`
- **Managed by**: `pm2 list`
- **Endpoints**:
  - `POST /api/search` — Performs semantic search for patents.
  - `POST /api/extract-terms` — Extracts key terms from text using the Ollama backend.
  - `GET /api/get-status` — Reports job progress or system health.
  - `GET /health` — Simple health check endpoint.
- **Config**: `ecosystem.config.js`
- **Logs**: `pm2 logs search-service`

---

### `~/vectorization/` (Data Processing)
- **Purpose**: GPU-accelerated Python scripts to convert patent XML data into vector embeddings.
- **Key Script**: `vectorize_gpu.py`

---

### `~/scripts/` (Utility Scripts)
- **Purpose**: Helper, setup, and monitoring scripts for the project.
- **Contains**:
  - `setup-ollama.sh`: Installs the Ollama service and pulls the required model for the `/api/extract-terms` endpoint.
  - `watch_vector_progress.sh`: A real-time monitor to track the progress of the vectorization process.

---

### `~/qdrant_storage/` (Vector Database)
- **Purpose**: Persistent storage for the Qdrant vector database.  
  This directory is mounted into the Qdrant Docker container.  
  **Do not delete this directory, as it contains all indexed patent data.**

---

### `/mnt/storage_pool/` (Raw Data Storage)
- **Purpose**: Unified data pool for storing raw patent data downloaded from various jurisdictions.
- **Subdirectories**:
  - `uspto/`, `epo/`, `cnipa/` — Patent data organized by jurisdiction.
  - `download_state/` — Download logs and state-tracking files.

---

# Data Workflow Overview

The pipeline automates patent data acquisition, processing, and indexing into Qdrant.

---

## 0. Initial Setup

Before starting the data workflow, ensure the base environment is configured by running the setup script:

```bash
./vm-setup.sh
```

If you intend to use the `/api/extract-terms` endpoint, you must also install and configure the Ollama service:

```bash
cd ~/scripts && ./setup-ollama.sh
```

---

## 1. Download Phase

This phase downloads bulk patent data archives for a specific jurisdiction and year.

**Script:** `~/patent-search/download-data.sh`  
**Usage:** The script is resumable and will skip already completed files.

**Example:**
```bash
cd ~/patent-search && ./download-data.sh uspto 2024
```

**Features:**
- Resumable downloads are tracked via `.download_state_<year>.txt`.
- Validates `.tar` and extracts nested `.ZIP` archives.
- Deletes all non-XML files after extraction to conserve disk space.
- Logs detailed progress to `/mnt/storage_pool/<jurisdiction>/download_<year>.log`.

---

## 2. Vectorization Phase

This phase reads the downloaded XML files, converts their text content into vector embeddings using a sentence-transformer model, and saves them to the Qdrant database.

**Script:** `~/vectorization/vectorize_gpu.py`  
**Usage:** This is a long-running, GPU-intensive process. It is safe to stop and restart; it will skip already indexed files.

**Run Command:**
```bash
cd ~/vectorization && python3 vectorize_gpu.py
```

---

## Monitoring Progress (Optional but Recommended)

To monitor the progress of the vectorization script, open a new terminal session and run:

```bash
cd ~/scripts && ./watch_vector_progress.sh
```

**Features:**
- GPU-accelerated via SentenceTransformer.
- Multi-GPU support for faster processing.
- Resume-safe; it checks for existing vector IDs in Qdrant before processing.
- Built-in retry logic for Qdrant upserts to handle temporary network issues.
