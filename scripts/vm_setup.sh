#!/bin/bash
set -e

echo "======================================"
echo "Patent Search Server Setup"
echo "======================================"

# Update system
echo "Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install Docker
echo "Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    rm get-docker.sh
    sudo usermod -aG docker $USER
    echo "Docker installed. You may need to log out and back in for group changes."
else
    echo "Docker already installed."
fi

# Install
echo "Installing Docker Compose..."
sudo apt-get install -y docker-compose-plugin
sudo apt-get install -y python3 python3-pip python3-venv
sudo apt-get install -y wget curl unzip git htop jq bc

echo "Upgrading pip and installing Python packages..."
python3 -m pip install --user --upgrade pip
python3 -m pip install --user "sentence-transformers==5.1.1"

# Pre-download the embeddings model so the API can run offline
MODEL_DIR="$HOME/patent-search/api/models/all-MiniLM-L6-v2"
if [ -d "$HOME/patent-search" ]; then
    echo "Ensuring sentence-transformers model exists at $MODEL_DIR..."
    python3 - <<'PY'
from pathlib import Path
from sentence_transformers import SentenceTransformer

target = Path.home() / "patent-search" / "api" / "models" / "all-MiniLM-L6-v2"
if target.exists():
    print(f"Model already present at {target}")
else:
    target.parent.mkdir(parents=True, exist_ok=True)
    print("Downloading sentence-transformers/all-MiniLM-L6-v2 ...")
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    model.save(str(target))
    print(f"Model saved to {target}")
PY
else
    echo "Clone the patent-search repo into ~/patent-search before downloading the model."
fi

# NVIDIA container toolkit for GPU-aware Docker
echo "Configuring NVIDIA Container Toolkit..."
distribution=$(. /etc/os-release; echo ${ID}${VERSION_ID})
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/${distribution}/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

echo "Creating directories..."
mkdir -p ~/qdrant_storage
sudo chown -R $(whoami):$(whoami) ~/qdrant_storage

echo "Add the vectorize alias to ~/.bashrc if not already present:"
echo "  alias vectorize='~/patent-search/scripts/vectorize.sh'"
echo ""
echo "======================================"
echo "Setup Complete!"
echo "======================================"
