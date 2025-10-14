# Dockerfile.vectorizer-python-gpu - Python-based GPU vectorizer
# More reliable GPU support than Node.js transformers

FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

# Install Python 3.10
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy vectorization script
COPY vectorize_gpu.py ./

# Set environment for GPU
ENV CUDA_VISIBLE_DEVICES=0,1
ENV PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512

CMD ["python3", "vectorize_gpu.py"]
