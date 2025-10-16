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

## File Structure

```
~/api
├── main.py
└──routes/
└──services/
├── requirements.txt

~/vectorization/
└── vectorize_gpu.py

~/scripts/
├── setup-ollama.sh
└── watch_vector_progress.sh

~/qdrant_storage/
├── collections/
└── aliases/

/mnt/storage_pool/
├── uspto/
├── epo/
├── cnipa/
└── download_state/ 
```

## Data Workflow

1. **Download**: Bulk patent archives for a specific jurisdiction and year.  
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

Deployment to the VM is handled automatically whenever changes are pushed to the `main` branch.  
This is done via a GitHub Actions workflow using SSH and Docker Compose.

```yaml
name: Deploy to VM

on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Inspect code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Setup SSH
        uses: webfactory/ssh-agent@v0.9.0
        with:
          ssh-private-key: ${{ secrets.SSH_PRIVATE_KEY }}

      - name: Determine if rebuild is needed
        id: check
        run: |
          echo "Checking if Dockerfile or requirements changed..."
          CHANGED_FILES=$(git diff --name-only HEAD^ HEAD)
          echo "Files changed in this push: $CHANGED_FILES"

          if echo "$CHANGED_FILES" | grep -qE '(^Dockerfile$|^requirements\.txt$)'; then
            echo "rebuild=true" >> $GITHUB_OUTPUT
            echo "Rebuild is required."
          else
            echo "rebuild=false" >> $GITHUB_OUTPUT
            echo "Rebuild is not required."
          fi

      - name: Deploy on VM
        run: |
          ssh -o StrictHostKeyChecking=no ${{ secrets.SSH_USER }}@${{ secrets.SSH_HOST }} << 'EOF'
          set -e
          cd ~/patent-search
          sudo chown -R $USER:$USER .
          git fetch origin
          git reset --hard origin/main
          sudo docker builder prune -f
          sudo docker compose down
          sudo docker compose up --build -d
          sudo docker image prune -f
          EOF
```

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
