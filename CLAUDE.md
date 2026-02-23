# CardChecker — Pokemon Card Scanner & Pricer

## What This Does

Scan a Pokemon card with a photo → identify it → get market price from CardMarket.

## Pipeline

```
Photo → CLIP Embedding → FAISS Search → Card ID → Price Lookup → Response
```

## Tech Stack

- Python 3.11+
- CLIP (`openai/clip-vit-base-patch32`) — 512-dim image embeddings
- FAISS — fast similarity search
- FastAPI — REST API
- Data source: CardMarket (official CSVs + scraped images)

## Project Structure

```
CardRecognition/
├── scripts/
│   ├── download_cardmarket_csvs.py   # Step 1: get card catalog + prices
│   ├── scrape_cardmarket_images.py   # Step 2: download card images
│   └── build_embedding_index.py      # Step 3: build CLIP+FAISS index
├── src/
│   ├── recognizer.py                 # CardRecognizer class
│   └── api.py                        # FastAPI server
├── tests/
│   └── test_recognizer.py
├── data/cardmarket/                  # Downloaded data (gitignored)
│   ├── product_catalog.csv
│   ├── price_guide.csv
│   ├── cards_with_prices.json
│   └── images/*.jpg
├── models/card_index/                # Built index (gitignored)
│   ├── cards.faiss
│   └── metadata.pkl
├── requirements.txt
└── CLAUDE.md
```

## How to Run (Step by Step)

```bash
# 1. Create venv & install deps
py -3.11 -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt

# 2. Download CardMarket CSVs (catalog + prices)
#    NOTE: CardMarket is behind Cloudflare.
#    Download manually from https://www.cardmarket.com/en/Pokemon/Data/Download
#    Save as: data/cardmarket/product_catalog.csv  and  data/cardmarket/price_guide.csv
#    Then run the script to filter/merge:
python scripts/download_cardmarket_csvs.py

# 3. Download card images via Pokemon TCG API (free, legal, HD)
python scripts/download_images_pokemontcg.py

# 4. Build CLIP embedding index
python scripts/build_embedding_index.py

# 5. Start API server
python src/api.py
# → http://localhost:8000
# → Docs: http://localhost:8000/docs
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Index stats, model info |
| POST | `/identify` | Upload photo → top match + alternatives + prices |
| GET | `/card/{id}` | Card details by CardMarket product ID |

## Scope (MVP)

- **2025 sets only** (~60 expansions, ~7-8K cards)
- CardMarket scraping with rate limiting (1.5s delay, 3 workers)
- JSON files for data storage (no DB needed for this scale)
- Multi-crop recognition for better accuracy

## Key Design Decisions

- Embeddings are L2-normalised → cosine similarity via inner product
- Multi-crop voting: original + 90% crop + 80% crop → more robust
- Scraper is resumable: skips already-downloaded images
- Small index (<10K) uses `IndexFlatIP` (exact search); larger uses IVF
