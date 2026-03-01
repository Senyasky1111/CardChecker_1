"""Centralized configuration loader for API keys and settings."""

import os
from pathlib import Path

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

# API Keys
POKETRACE_API_KEY = os.getenv("POKETRACE_API_KEY", "")
POKEMON_API_RAPIDAPI_KEY = os.getenv("POKEMON_API_RAPIDAPI_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# API Base URLs
POKETRACE_BASE_URL = "https://api.poketrace.com/v1"
POKEMON_API_BASE_URL = "https://pokemon-tcg-api.p.rapidapi.com"

# Rate limits
POKETRACE_BURST_DELAY = 0.35   # ~3 req/s (30 req/10s)
POKEMON_API_DELAY = 0.25       # ~4 req/s (300 req/min)
