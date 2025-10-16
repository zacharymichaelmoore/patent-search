#!/bin/bash

# Install Ollama on your VM
# Run this on patent-search-vm

echo "Installing Ollama..."
curl -fsSL https://ollama.com/install.sh | sh

echo "Pulling Llama 3.1 8B model..."
ollama pull llama3.1-gpu-optimized:latest

echo "Testing Ollama..."
ollama run llama3.1-gpu-optimized:latest "Extract key terms from: AI-powered smartphone camera"

echo "Starting Ollama as a service..."
# Ollama runs on port 11434 by default
# Make it available to your Next.js app

echo "Setup complete!"
echo "Ollama is running on http://localhost:11434"
echo ""
echo "Test it with:"
echo "curl http://localhost:11434/api/generate -d '{\"model\": \"llama3.1-gpu-optimized:latest\", \"prompt\": \"test\"}'"
