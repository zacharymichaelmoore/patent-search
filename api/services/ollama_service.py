import itertools
import os

OLLAMA_PORTS = [11430, 11431, 11432, 11433, 11434, 11435, 11436, 11437]
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://host.docker.internal")
OLLAMA_URLS = [f"{OLLAMA_HOST}:{p}/api/generate" for p in OLLAMA_PORTS]
_ollama_cycle = itertools.cycle(OLLAMA_URLS)


def get_next_ollama_url() -> str:
    """Round-robin load balancing across all GPU-bound Ollama services."""
    return next(_ollama_cycle)
