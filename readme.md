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