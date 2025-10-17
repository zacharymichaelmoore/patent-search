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
sudo apt-get install -y wget curl unzip git htop

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
