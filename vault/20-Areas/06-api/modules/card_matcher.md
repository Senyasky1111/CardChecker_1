---
type: module
status: active
source: src/card_matcher.py
lines: 690
related: [[ocr]], [[card_detector]], [[recognizer]], [[db]], [[../endpoints/identify-v2]]
area: [backend, recognition]
tags: [module, matching, ocr, sql, clip]
created: 2026-05-21
updated: 2026-05-21
---

# card_matcher.py

> **TL;DR**: Heart of `/identify-v2`. OCR-first pipeline → SQL exact lookup → CLIP fallback/rerank. Supports EN/JP/TW.

## Public surface

- `MatchResult` (dataclass) — `success`, `method`, `card`, `candidates`, `ocr_name`, `ocr_number`, `language`, `confidence`, `processing_time_ms`
- `CardMatcher` — main class:
  - `match(image: PIL.Image) → MatchResult`
  - `get_card_by_id(cm_id_product) → dict`
  - Properties (lazy): `conn`, `ocr`, `detector`, `doctr_detector`, `card_count`

## Internal flow

1. **Detect** boundary (YOLO → DocTR fallback) + perspective correct → 600×825
2. **OCR** name + collector number + language (Tesseract → EasyOCR fallback)
3. **DocTR fallback** если YOLO OCR не нашёл number
4. **SQL lookup** — strategy ladder (most specific first):
   - `number + set code`
   - `number + total + language`
   - `number + name filter`
   - `name only`
5. **CLIP fallback** когда SQL ничего не нашёл (visual search с threshold)
6. **CLIP rerank** когда multiple candidates с тем же именем → pick by visual similarity
7. **Name fuzzy-matching** (rapidfuzz) с language tiebreaker: **JP > EN > TW**

## Confidence values

| Method | Confidence |
|--------|-----------|
| OCR exact (number + name) | 0.95 |
| OCR name only | 0.7–0.99 |
| CLIP fallback | 0.75 |
| Number only, no name | 0.35–0.7 (forces Gemini fallback) |

## Dependencies

- `src.card_detector` — `get_detector()`, `DetectionResult`
- `src.db` — `get_connection()` для sqlite3
- `src.ocr` — `CardOCR`, `CardOCRResult`, `CollectorNumber`
- `rapidfuzz` для fuzzy matching
- `PIL`, `numpy`, `sqlite3`

## Notable patterns

- **Lazy init** всех heavy deps (detector, ocr, doctr, recognizer)
- **CLIP reuse**: `index.reconstruct()` вместо reload images (perf)
- **Language-aware** SQL queries with optional filter
- **Dedup** by `tcgdex_id` в CLIP результатах
- **Safety net**: single-candidate CLIP verification если name fuzzy < 55 (holographic OCR artifact mitigation)

## Open issues

- Line 227-248, 285-295: CLIP safety net требует чтобы recognizer был set
- Line 313-329: confidence dip (0.35-0.7) когда OCR name = None но number есть

## Связанные

- API: [[../endpoints/identify-v2]]
- OCR: [[ocr]]
- Detection: [[card_detector]], [[yolo_card_detector]], [[doctr_detector]]
- CLIP: [[recognizer]]
- DB schema: [[db]]
