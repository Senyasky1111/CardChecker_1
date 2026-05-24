# CardCheck Backend — Production Dockerfile
# Optimized for Hetzner Cloud (CAX21 ARM or CCX x86)

FROM python:3.11-slim

# System dependencies for OpenCV, EasyOCR, Tesseract
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-jpn \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code + scripts
COPY src/ src/
COPY scripts/ scripts/
COPY static/ static/

# Copy data files (NOT images — only JSON/DB)
COPY data/cardmarket/cards_with_prices.json data/cardmarket/
COPY data/cardmarket/products_singles.json data/cardmarket/
COPY data/cardmarket/_tcgdex_match_map.json data/cardmarket/
COPY data/cardmarket/_tcgdex_cache_en.json data/cardmarket/
COPY data/cardmarket/_tcgdex_cache_ja.json data/cardmarket/
COPY data/cardmarket/_tcgdex_cache_zh-tw.json data/cardmarket/
COPY data/cardmarket/_expansion_map.json data/cardmarket/
COPY data/cardmarket/_set_abbreviations.json data/cardmarket/
COPY data/cardmarket/_cm_products_all.json data/cardmarket/
COPY data/cardmarket/_pricecharting_set_map.json data/cardmarket/
COPY data/cardmarket/price_guide.json data/cardmarket/

# Copy model files
COPY models/card_index/ models/card_index/
COPY models/yolo_card/ models/yolo_card/

# EasyOCR downloads models on first run — pre-download them
RUN python -c "import easyocr; easyocr.Reader(['en', 'ja'])" 2>/dev/null || true

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# Start with uvicorn — 2 workers for concurrency
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
