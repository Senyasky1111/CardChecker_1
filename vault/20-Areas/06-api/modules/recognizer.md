---
type: module
status: active
source: src/recognizer.py
lines: 646
related: [[card_matcher]], [[text_index]], [[../endpoints/identify]]
area: [backend, recognition, ml]
tags: [module, clip, faiss, embedding]
created: 2026-05-21
updated: 2026-05-21
---

# recognizer.py

> **TL;DR**: CLIP-based card recognition через pretrained FAISS index. 3 модa: single-shot, multi-crop voting, hybrid (CLIP + OCR). Legacy для `/identify`, fallback в `/identify-v2`.

## Public surface

- `CardRecognizer` — FAISS index wrapper:
  - `identify(image, k=5) → list[dict]` — single-shot CLIP
  - `identify_multi_crop(image) → list[dict]` — 3-crop voting
  - `identify_hybrid(image) → (list[dict], ocr_info)` — CLIP + OCR merge
  - `get_card(id_product) → dict` — lookup by CardMarket id
  - `search_filtered(embedding, collector_number, language, k)` — CLIP с optional number pre-filtering
- `CardRecognizer.load(index_dir) → CardRecognizer` (classmethod)

## Internal flow

### Embedding
- CLAHE на L канале (LAB)
- Gray-world white balance
- Square padding (preserves aspect ratio, не squashing)

### Search
- Если `collector_number` provided: build number lookup (cached), direct similarity на candidates (faster than full FAISS)
- Иначе: full FAISS search (normalized L2)
- Dedup by `product_id` (multiple language images → same card)

### Multi-crop voting
- 3 crops: original, 95% center, 90% center
- Vote by `product_id`
- Rank by votes → confidence

### Hybrid
- CLIP top-50 + OCR lookup → merge by `product_id`
- Re-rank: CLIP weight 0.4 + OCR weight 0.6 (configurable)
- Strong OCR match (≥0.8) gets boosted confidence

## Model

- Path: `models/card_index/`
- `cards.faiss` — FAISS L2 index
- `metadata.pkl` — card metadata (product_id → card_dict)
- `cards_indexed.json` — indexed cards manifest
- CLIP model: загружается из metadata (typically `openai/clip-vit-base-patch32`)

## Dependencies

- `faiss` — index search, `index.reconstruct()` для embedding lookup
- `torch`, `transformers` — `CLIPModel`, `CLIPProcessor`
- `src.cardmarket_url` — `card_url()` для marketplace links
- `src.ocr` — `CardOCR` (lazy)
- `src.text_index` — `CardTextIndex` (lazy)
- `PIL`, `numpy`

## Notable patterns

- **Lazy init**: ocr, text_index, number lookup
- **FAISS reconstruction caching**: `_tcgdex_to_faiss_idx` dict built once
- **Backward-compat metadata**: handles old format keyed by product_id
- **Old (slow) CLIPProcessor** used умышленно (matches training embeddings, new fast processor drifts accuracy)

## Производительность

- Single-shot identify: ~500ms-1s (CLIP forward + FAISS)
- Multi-crop: ~1.5-2.5s
- Hybrid (с OCR): ~1-3s

## Связанные

- Wrapped by: [[card_matcher]] (для CLIP rerank / fallback)
- API: [[../endpoints/identify]] (direct), [[../endpoints/identify-v2]] (via matcher)
- Text index: [[text_index]]
- Build index: `scripts/build_embedding_index.py`
- Fine-tuning: [[../../09-ml-research/clip-finetuning/strategy]]
