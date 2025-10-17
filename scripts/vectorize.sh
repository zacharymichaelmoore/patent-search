#!/usr/bin/env bash
set -euo pipefail

docker build -f "$(dirname "$0")/../vectorization/Dockerfile" -t patent-vectorizer vectorization
docker run --rm --gpus all \
  --add-host=host.docker.internal:host-gateway \
  -v /mnt/storage_pool/uspto:/data:ro \
  -e QDRANT_HOST=host.docker.internal \
  "$@" \
  patent-vectorizer

# make sure to run `chmod +x scripts/vectorize.sh`
# then add to the ` ~/.bashrc` the following:
# `alias vectorize='~/patent-search/scripts/vectorize.sh'`