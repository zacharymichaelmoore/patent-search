# README

## System

**Downloading and Vectorization**  
  Downloads bulk patent data and converts it into vector embeddings.
  TODO: This process will run nightly


**FastAPI Search Service**  
  Searches vector store and passes too ollama for scoring, returning relevant results.

**Single file frontend**  
  It's just one html file with js and css inlined.

**Qdrant**  
  Vector database for storing the embeddings.

**Ollama**  
  Hosts and serves a model named `llama3.1-gpu-optimized`

---

## Data Workflow

1. **Download**: The download script uses the uspto bulk api (only uspto for now).
It downloads the file, then unzips everything and then removes everything except the xml file. 
   - **Script**: `~/patent-search/download-data.sh`  
   - **Example**:  
     ```bash
     cd ~/patent-search && ./download-data.sh uspto 2024
     ```

2. **Vectorize**: Process the downloaded XML files into vector embeddings and store them in Qdrant.  
   - **Script**: `~/vectorization/vectorize_gpu.py`  
   - **Model**: `all-MiniLM-L6-v2` (SentenceTransformer)

  Make sure to run `chmod +x scripts/vectorize.sh` then add to the ` ~/.bashrc` the following:
  `alias vectorize='~/patent-search/scripts/vectorize.sh'`

---

## Fresh VM Bootstrap

1. **Clone repo & enter workspace**
   ```bash
   git clone <repo-url> ~/patent-search
   cd ~/patent-search
   ```
2. **Run the setup script** (`scripts/vm_setup.sh`) – installs Docker/Compose, NVIDIA container toolkit, common packages, and prepares `~/qdrant_storage`.
   ```bash
   bash scripts/vm_setup.sh
   ```
3. **Bundle the embedding model** – the setup script installs `sentence-transformers==5.1.1` and will download `all-MiniLM-L6-v2` into `api/models/` when the repo exists at `~/patent-search`. If you need to refresh manually, run:
   ```bash
   python3 -m pip install "sentence-transformers==5.1.1"
   python3 - <<'PY'
   from sentence_transformers import SentenceTransformer
   from pathlib import Path
   target = Path.home() / "patent-search" / "api" / "models" / "all-MiniLM-L6-v2"
   target.parent.mkdir(parents=True, exist_ok=True)
   SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2").save(str(target))
   PY
   ```
   Rebuild the Docker image (`docker build -t patent-app:latest .`) whenever the on-disk model changes.
4. **Enable vectorizer alias** – append the alias shown above to `~/.bashrc`, then reload your shell: `source ~/.bashrc`. Log out/in once so Docker group membership takes effect.
5. **Provision Ollama model** – follow the commands in the next section to install Ollama and create `llama3.1-gpu-optimized`.
6. **Launch core services** – from the repo root run `docker compose up -d` to start `patent-app` and `qdrant`.
7. **Vectorization workflow** – place USPTO XML dumps under `/mnt/storage_pool/uspto`, open a screen window, and run `vectorize` to build the container and ingest data into Qdrant.

## Setup and Configuration

### 1. VM and Ollama Setup

```bash
./vm-setup.sh

cd ~/scripts && ./setup-ollama.sh

cat > ~/Modelfile << 'EOF'
FROM llama3.1:8b-instruct-q6_K
PARAMETER num_gpu 999
PARAMETER num_thread 48
EOF

ollama create llama3.1-gpu-optimized -f ~/Modelfile
```

---

### 2. Environment

```bash
export QDRANT_URL="http://localhost:6333"
export OLLAMA_URL="http://localhost:11434/api/generate"
export QDRANT_COLLECTION="uspto_patents"
export OLLAMA_CONCURRENCY=32
export QDRANT_FETCH_COUNT=100
export HIGH_SCORE_THRESHOLD=60
```

---

> The API loads the sentence-transformer from `api/models/all-MiniLM-L6-v2` by default. Set `EMBED_MODEL_NAME` if you keep the model in a different location.

---

## Deployment

Edit local files and connect to qdrant data through ngrok. This will allow for local testing
and development.

Push to main branch to deploy to vm through a github action. This will run the `docker-compose.yml`
as opposed to the `docker-compose.dev.yml` which is for local development.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|-----------|-------------|
| **GET** | `/` | Serves the main HTML frontend |
| **POST** | `/api/search` | Initiates a patent search and streams results |
| **POST** | `/api/search/enqueue` | Reserves a search slot and returns queue status |
| **POST** | `/api/extract-terms` | Extracts key terms using the LLM |
| **POST** | `/api/generate-description` | Generates invention descriptions |
| **GET** | `/health` | Health check endpoint |
| **GET** | `/export_csv` | Exports search results to CSV |

---

## Local Development

### Run the backend on the VM, edit the frontend locally

1. **Ensure services are running on the VM**  
   ```bash
   ssh zacharymoore@34.182.86.63
   cd ~/patent-search
   docker compose up -d
   ```

2. **Open an SSH tunnel from your laptop**  
   ```bash
   ssh -i ~/.ssh/google_compute_engine \
       -L 8000:localhost:8091 \
       zacharymoore@34.182.86.63
   ```
   Leave this session open. It forwards `localhost:8000` on your laptop to the FastAPI service running on the VM.

3. **Serve the frontend locally**  
   ```bash
   cd /Users/zacharymoore/Documents/GitHub/patent-search/frontend
   python3 -m http.server 8080
   ```

4. **Develop the UI**  
   - Visit `http://localhost:8080` in your browser. The page is served from your local `frontend/index.html`.  
   - All API calls are proxied to `http://localhost:8000` (through the SSH tunnel), so heavy compute still runs on the VM.  
   - Save edits to `index.html` and refresh the browser (⌘⇧R) to see changes instantly.

5. **Testing**  
   - `http://localhost:8000/health` confirms the backend is reachable.  
 - `curl http://localhost:8080/index.html | head` shows the exact HTML being served locally.

6. **Cleanup**  
  - Stop the static server with `Ctrl+C`.  
  - Close the tunnel by exiting the SSH session (`Ctrl+C`).

> Tip: if you need automatic refresh, swap `python3 -m http.server` with a watcher such as `live-server` or Vite.

### Run the backend locally against VM services

Use this when you want to exercise new API code (for example, the search queue) without deploying.

1. **Copy the embedding model once**
   ```bash
   scp -r -i ~/.ssh/google_compute_engine \
     zacharymoore@34.182.86.63:/home/zacharymoore/patent-search/api/models/all-MiniLM-L6-v2 \
     /Users/zacharymoore/Documents/GitHub/patent-search/api/models/
   ```

2. **Open an SSH tunnel to Qdrant and Ollama on the VM**
   ```bash
   ssh -i ~/.ssh/google_compute_engine \
       -L 6333:localhost:6333 \
       -L 11434:localhost:11434 \
       zacharymoore@34.182.86.63
   ```
   Leave this session open.

3. **Start Uvicorn locally**
   ```bash
   cd /Users/zacharymoore/Documents/GitHub/patent-search
   source .venv/bin/activate
   export QDRANT_URL=http://localhost:6333
   export OLLAMA_URL=http://localhost:11434/api/generate
   uvicorn api.main:app --reload --port 9000
   ```

4. **Test the search queue**
   ```bash
   for i in {1..6}; do
     curl -s -X POST http://localhost:9000/api/search/enqueue \
       -H 'Content-Type: application/json' \
       -d '{"userDescription":"test gadget","maxDisplayResults":15}'
     echo
   done
   ```
   The first five responses should include `"granted": true`, and the sixth should return `"queued": true` with `queueToken` and `queuePosition`.

5. **Consume a granted slot**
   ```bash
   curl -N "http://localhost:9000/api/search?userDescription=test%20gadget&maxDisplayResults=15&queueToken=REPLACE_WITH_GRANTED_TOKEN"
   ```
   Cancel the stream with `Ctrl+C` to release the slot. Queued tokens can be polled again via `/api/search/enqueue` until they are granted.

6. **Cleanup**
   - Stop Uvicorn with `Ctrl+C`.
   - Close the SSH tunnel session.
