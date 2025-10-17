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
echo "Creating directories..."
mkdir -p ~/qdrant_storage
sudo chown -R $(whoami):$(whoami) ~/qdrant_storage
echo ""
echo "======================================"
echo "Setup Complete!"
echo "======================================"
