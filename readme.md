# README

## System

**Downloading and Vectorization**  
  Scripts download bulk patent data and converts it into vector embeddings.

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

## Fresh VM

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

### 1. VM Setup

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

Pushing to main branch automatically deploys through a github action. This will run the `docker-compose.yml`
as opposed to the `docker-compose.dev.yml` which is for local development.

## API 
Swagger UI at `http://<host>/docs`
ReDoc at `http://<host>/redoc`

## Local Development

1. **Copy the embedding model once**  
   ```bash
   scp -r -i ~/.ssh/google_compute_engine \
     <USER>@<SERVER_ADDRESS>:/home/<USER>/patent-search/api/models/all-MiniLM-L6-v2 \
     /Users/<USER>/Documents/GitHub/patent-search/api/models/
   ```

2. **Open an SSH tunnel to Qdrant and Ollama**  
   ```bash
   ssh -i ~/.ssh/google_compute_engine \
       -L 6333:localhost:6333 \
       -L 11434:localhost:11434 \
       <USER>@<SERVER_ADDRESS>
   ```
   Leave this terminal open for the entire session.

3. **Start the backend**  
   ```bash
   cd /Users/zacharymoore/Documents/GitHub/patent-search
   source .venv/bin/activate
   export QDRANT_URL=http://localhost:6333
   export OLLAMA_URL=http://localhost:11434/api/generate
   export SEARCH_MAX_CONCURRENT=5
   export SEARCH_QUEUE_STALE_SECONDS=180
   uvicorn api.main:app --reload --port 9000
   ```

4. **Serve the frontend**  
   ```bash
   cd frontend
   python3 -m http.server 8080
   ```

5. **Develop & test**  
   - Visit `http://localhost:8080`. The page is served from your local `frontend/index.html`.  
   - All fetches hit `http://localhost:9000`, which runs on your laptop and calls the VM through the tunnel.  
   - Queue logic can be exercised directly via `/api/search/enqueue` while watching the UI banner.

6. **Cleanup**  
   - Stop the static server (`Ctrl+C`).  
   - Stop Uvicorn (`Ctrl+C`).  
   - Close the tunnel session.  

> Tip: swap `python3 -m http.server` with a watcher such as `live-server`.
