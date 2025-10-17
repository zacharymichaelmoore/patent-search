# GPU-enabled vectorizer runnable via `docker run --gpus all`
FROM nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

# Install Python 3.10 and common native deps required by sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3-pip \
    python3-venv \
    build-essential \
    git \
    curl \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Alias python3/pip3 to python/pip for consistency
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1 \
    && update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

# Copy vectorization script
COPY vectorize_gpu.py ./

# Default runtime configuration; override at docker run if needed
ENV DATA_DIR=/data \
    QDRANT_HOST=qdrant \
    QDRANT_PORT=6333 \
    PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512

CMD ["python", "vectorize_gpu.py"]
