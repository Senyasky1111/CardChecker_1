---
type: catalog
status: active
area: [data-pipelines, infrastructure]
tags: [scripts, catalog, sweeping]
created: 2026-05-23
updated: 2026-05-23
---

# Scripts Catalog

> Полный inventory `scripts/` (57 файлов). Одна строка на script. По категориям.

Эта заметка — **sweeping reference**, не per-script docs. Для важных pipelines смотри dedicated runbooks и под-MOC'и в [[_MOC]].

## CardMarket (7)

| Script | Lines | Purpose |
|--------|-------|---------|
| `scripts/scrape_cardmarket_images.py` | 357 | Scrape card images from CardMarket product pages (3 workers, 1.5s delay) |
| `scripts/scrape_cm_all_products.py` | 459 | Scrape complete CM product catalog for singles via pagination |
| `scripts/download_cardmarket_csvs.py` | 315 | Parse downloaded products_singles.json + price_guide.json → cards_with_prices.json |
| `scripts/fetch_cardmarket_urls.py` | 422 | Construct CM product URLs from normalized names + expansion IDs |
| `scripts/match_cm_products.py` | 686 | Match local DB to CM product catalog (fuzzy) |
| `scripts/fill_prices_from_csv.py` | 221 | Merge CM CSV price data into database |
| `scripts/_fix_duplicate_cmids.py` | 99 | Deduplicate CardMarket IDs in DB |

→ [[cardmarket/overview]]

## PriceCharting (5)

| Script | Lines | Purpose |
|--------|-------|---------|
| `scripts/scrape_pc_sets.py` | 272 | Discover JP/TW set slugs via category pages, auto-map to set_ids |
| `scripts/build_pricecharting_map.py` | 674 | Comprehensive slug → set_id mapping with JP/CN/TW validation |
| `scripts/fetch_urls_cdp.py` | 332 | Fetch PC URLs via Chrome DevTools Protocol (headless browser) |
| `scripts/resolve_pricecharting_urls.py` | 306 | Resolve PC slugs to final product URLs with dedup |
| `scripts/_fix_pc_urls.py` | 105 | Fix PC URLs for JP/TW (remove abbreviation codes) |

→ [[pricecharting/overview]]

## Pokemon API & Image Download (3)

| Script | Lines | Purpose |
|--------|-------|---------|
| `scripts/scrape_pokemon_card_jp.py` | 429 | Scrape JP Pokemon cards from Pokemon TCG API |
| `scripts/scrape_pokemon_card_tw.py` | 395 | Scrape TW cards from Pokemon TCG API |
| `scripts/download_images_pokemontcg.py` | 345 | Batch download HD card images from TCGdex (15 workers, EN/JA/ZH-TW/ZH-CN) |

## TAG Grading Scraper (1)

| Script | Lines | Purpose |
|--------|-------|---------|
| `scripts/scrape_tag.py` | **1472** | TAG grading reports scraper (DIG) — metadata + YOLO annotations. **Flagship script.** |

→ [[tag-scraping/overview]]

## eBay Photo Scraping (1)

| Script | Lines | Purpose |
|--------|-------|---------|
| `scripts/scrape_ebay_photos.py` | 329 | Real-world card photos from eBay via Apify (anti-bot, headless) |

→ [[ebay-scraping/overview]]

## Database Building (4)

| Script | Lines | Purpose |
|--------|-------|---------|
| `scripts/build_card_database.py` | 468 | Build SQLite DB from TCGdex API (sets + cards + prices), resumable tiered fetch |
| `scripts/build_embedding_index.py` | 438 | Build FAISS index of CLIP embeddings (768-dim ViT-L/14) |
| `scripts/enrich_metadata.py` | 292 | Add set/rarity/type metadata via TCGdex |
| `scripts/populate_set_expansion_ids.py` | 137 | Populate TCGdex expansion IDs for known sets |

## Pricing Enrichment (5)

| Script | Lines | Purpose |
|--------|-------|---------|
| `scripts/enrich_poketrace.py` | 410 | PokeTrace Pro: TCGPlayer/CM IDs, prices USD/EUR + PSA/BGS/CGC |
| `scripts/enrich_pokemon_api.py` | 350 | Pokemon-API pricing + availability |
| `scripts/enrich_us_market.py` | 241 | TCGPlayer US market pricing |
| `scripts/fill_tcgplayer_ids.py` | 327 | Fill TCGPlayer product IDs для US cards |
| `scripts/update_prices_daily.py` | **839** | **Daily price sync** — all cards from PokeTrace + Pokemon-API + CM CSV. Scheduled task. |

→ [[runbooks/daily-price-update]]

## Name & Language Processing (3)

| Script | Lines | Purpose |
|--------|-------|---------|
| `scripts/fill_eng_names_gemini.py` | 320 | Translate JP/TW Trainer/Supporter names → official EN via Gemini |
| `scripts/fill_cross_language.py` | 439 | Cross-reference + validate names across EN/JA/ZH-TW |
| `scripts/self_fill_eng_name.py` | 100 | Regex-based EN name auto-fill для common patterns |

## Training & Model Export (6)

| Script | Lines | Purpose |
|--------|-------|---------|
| `scripts/generate_yolo_dataset.py` | 545 | Composite synthetic YOLO-pose dataset |
| `scripts/generate_training_pairs.py` | 298 | Synthetic CLIP fine-tune positive pairs |
| `scripts/train_yolo_card.py` | 131 | Train YOLOv8n-pose card detector (bbox + 4 corners) |
| `scripts/train_defect_yolo.py` | 296 | Train YOLOv11m on TAG dataset (7 defect classes) |
| `scripts/finetune_clip.py` | 225 | Fine-tune CLIP ViT-L/14 vision encoder |
| `scripts/export_yolo_onnx.py` | 107 | Export YOLO PyTorch → ONNX |

→ [[../09-ml-research/_MOC|ML Research MOC]] для context.

## Testing & Validation (10)

| Script | Lines | Purpose |
|--------|-------|---------|
| `scripts/test_100_cards.py` | 331 | E2E test 100 sample cards: identify → price lookup → verify |
| `scripts/test_api_detect.py` | 98 | Test `/detect-card` + `/identify-v2` endpoints |
| `scripts/test_card_detection.py` | 283 | Card detection accuracy on sample images |
| `scripts/test_e2e_pipeline.py` | 323 | Full pipeline: scan → identify → grade → collect |
| `scripts/test_gemini.py` | 138 | Gemini identification accuracy |
| `scripts/test_number_detection.py` | 221 | Collector number OCR extraction |
| `scripts/run_gemini_test.py` | 84 | Quick inline Gemini grading test |
| `scripts/_test_cards.py` | 42 | Query PokeTrace для specific cards |
| `scripts/_test_urls.py` | 66 | Validate constructed URLs vs real CM endpoints |
| `scripts/_test_url_http.py` | 27 | Test CM URL format variants |

## Checks & Diagnostics (9)

| Script | Lines | Purpose |
|--------|-------|---------|
| `scripts/benchmark_detectors.py` | 464 | Benchmark detection models (accuracy, speed, memory) |
| `scripts/check_coverage.py` | 72 | How many cards have prices / images |
| `scripts/_check_db.py` | 39 | DB status + row counts |
| `scripts/_check_enrichment.py` | 60 | PokeTrace enrichment completion |
| `scripts/_check_jp_sets.py` | 56 | JP-exclusive sets, coverage gaps |
| `scripts/_check_url_data.py` | 56 | URL data coverage per set |
| `scripts/_compare_slugs.py` | 62 | Constructed vs scraped slugs accuracy |
| `scripts/_expansion_coverage.py` | 53 | Calculate scraping priority per expansion |
| `scripts/_auto_map_pc.py` | 103 | Auto-map set_ids → PC slugs with validation |

## Data Repair (3)

| Script | Lines | Purpose |
|--------|-------|---------|
| `scripts/_reenrich_cleared.py` | 207 | Re-enrich cards с cleared enrichment data |
| `scripts/_test_search_url.py` | 64 | Test search URL generation pre-bulk-fix |

(`_fix_duplicate_cmids.py`, `_fix_pc_urls.py` listed under CardMarket / PriceCharting.)

---

## Conventions

- `_` префикс — utility / one-shot / diagnostic. Не для регулярного run.
- `scrape_*` — fetch from external service
- `enrich_*` — add data to existing DB rows
- `fill_*` — populate missing fields
- `build_*` — construct from scratch
- `test_*` — validation, not unit tests (real tests в `tests/`)
- `train_*` — ML training entry points

## When new script lands

Update this catalog. One row, one line. Don't write a per-file note unless the script is non-trivial (>300 lines + production-critical).
