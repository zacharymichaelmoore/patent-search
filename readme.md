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
2. **Run the setup script** (`scripts/vm_setup.sh:1-49`) – installs Docker/Compose, NVIDIA container toolkit, common packages, and prepares `~/qdrant_storage`.
   ```bash
   bash scripts/vm_setup.sh
   ```
3. **Enable vectorizer alias** – append the alias shown above to `~/.bashrc`, then reload your shell: `source ~/.bashrc`. Log out/in once so Docker group membership takes effect.
4. **Provision Ollama model** – follow the commands in the next section to install Ollama and create `llama3.1-gpu-optimized`.
5. **Launch core services** – from the repo root run `docker compose up -d` to start `patent-app` and `qdrant`.
6. **Vectorization workflow** – place USPTO XML dumps under `/mnt/storage_pool/uspto`, open a screen window, and run `vectorize` to build the container and ingest data into Qdrant.

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
| **POST** | `/api/extract-terms` | Extracts key terms using the LLM |
| **POST** | `/api/generate-description` | Generates invention descriptions |
| **GET** | `/health` | Health check endpoint |
| **GET** | `/export_csv` | Exports search results to CSV |
