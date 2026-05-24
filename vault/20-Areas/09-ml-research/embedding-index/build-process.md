---
type: note
status: stable
area: [ml, recognition, infra]
tags: [clip, faiss, embeddings, index]
created: 2026-05-23
updated: 2026-05-23
---

# Embedding Index — Build Process

> FAISS index 768-dim CLIP embeddings для ~50K cards (используется как level-5 fallback в `/identify-v2`).

## Script

`scripts/build_embedding_index.py` (~438 строк).

## Pipeline

1. **Load catalog** из `data/cards.db` — все 50K+ карты с image paths
2. **For each card**:
   - Load image
   - Apply same warping pre-processing as `/identify-v2` runtime (см. [[../../30-Resources/adr/2026-05-23-clip-fallback-uses-warped-image|ADR: CLIP warps]])
   - Encode через CLIP ViT-L/14 vision encoder (pretrained, OpenAI weights)
   - L2-normalize embedding
3. **Build FAISS index** — flat L2 index (exact search since 50K is fine for `IndexFlatIP` ~10ms search)
4. **Save**:
   - `models/clip_index.faiss` — FAISS binary
   - `models/clip_id_map.json` — index_position → card_id mapping

## Model

- **CLIP**: ViT-L/14, 768-dim embeddings
- Loaded via OpenCLIP
- Eventually swap для fine-tuned weights когда finetune validated (см. [[../clip-finetuning/strategy]])

## Size

- Index: ~150 MB (50K × 768 × 4 bytes)
- ID map: ~5 MB JSON

## Build time

- ~30 min на CPU (M-class laptop) для full rebuild
- ~10 min на T4 GPU
- Incremental builds (нового set add) ещё не реализованы — currently full rebuild

## When to rebuild

- Добавили новый set / cards в catalog
- Сменили CLIP backbone или fine-tuned encoder
- Изменили warp canonical resolution
- Изменили image preprocessing pipeline

## FAISS choice

- **IndexFlatIP** (inner product, equivalent to cosine after L2 norm) — exact, 50K trivial
- Не нужны IVF / HNSW при таком scale
- Когда catalog > 500K — пересмотреть на HNSW

## Production usage

- Loaded by `src/recognizer.py` at startup
- Memory: ~150 MB resident
- Query latency: 10-20ms (search) + CLIP encoding (50-100ms на CPU)

## Related

- [[../clip-finetuning/strategy]]
- [[../../06-api/modules/recognizer]]
- [[../../01-recognition/matching/5-level-sql-lookup]]
- [[../../30-Resources/adr/2026-05-23-clip-fallback-uses-warped-image]]
