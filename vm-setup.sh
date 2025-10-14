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

# Install Docker Compose (modern version)
echo "Installing Docker Compose..."
sudo apt-get install -y docker-compose-plugin

# Install Python for local development (optional)
echo "Installing Python utilities..."
sudo apt-get install -y python3 python3-pip python3-venv

# Install useful utilities
echo "Installing utilities..."
sudo apt-get install -y wget curl unzip git htop

# Create necessary directories
echo "Creating directories..."
mkdir -p ~/qdrant_storage
sudo chown -R $(whoami):$(whoami) ~/qdrant_storage

# Note about USPTO data
echo ""
echo "======================================"
echo "Setup Complete!"
echo "======================================"
echo ""
echo "Next steps:"
echo "1. Ensure your USPTO data is mounted at /mnt/storage_pool/uspto"
echo "2. cd ~/patent-search"
echo "3. docker compose up -d"
echo ""
echo "Note: If you see permission errors, log out and back in for Docker group changes."
echo ""
