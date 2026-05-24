---
type: module
status: active
source: src/text_index.py
lines: 269
related: [[recognizer]], [[card_matcher]]
area: [backend, recognition]
tags: [module, text-index, fuzzy-match]
created: 2026-05-21
updated: 2026-05-21
---

# text_index.py

> **TL;DR**: Fast text lookup index для hybrid recognition. Maps normalized card names и (set_code, number) tuples to FAISS indices.

## Public surface

- `CardTextIndex`:
  - `lookup_by_name(name, threshold=75, limit=20) → [(idx, score)]`
  - `lookup_by_collector_number(number, set_code, total) → [idx]`
  - `lookup_combined(name, number) → [idx]`
  - `get_set_code(set_id) → code`
- Module-level: `normalize_name(name) → str`
- Classmethod: `CardTextIndex.load_set_abbreviations(path) → dict[set_id, code]`

## Internal flow

1. **Build на init**: iterate `cards_by_idx`
2. Index:
   - by name (normalized, exact + fuzzy)
   - by number (collector_number, optionally + set_code или set_id)
3. **Lookup**:
   - Collector number first (strong signal)
   - Intersect/extend с name fuzzy matches
4. Return FAISS indices для downstream

## Threshold

- Fuzzy match: 75% similarity
- Below → не возвращается

## Name normalization

- Remove brackets, parens
- Remove spaces
- Lowercase

## Lookup strategy (in `lookup_combined`)

Когда есть и number и name:
1. Получить candidates по number
2. Получить candidates по name fuzzy
3. **Intersect** (если есть пересечение) — наиболее уверенный match
4. Иначе **union** — broader fallback

## Dependencies

- `rapidfuzz.fuzz.ratio` — fuzzy matching
- `src.ocr.CollectorNumber`
- `json`, `re`

## Notable patterns

- **Lazy load** set abbreviations (JSON file)
- Collector number → code lookup с fallback to set_id (backward compat)
- Intersection strategy: prefer when both signals match

## Используется в

- `recognizer.py:identify_hybrid()` — OCR-based pre-filtering CLIP candidates
- В будущем: можно использовать в `card_matcher.py` для acceleration

## Связанные

- CLIP wrapper: [[recognizer]]
- Matching pipeline: [[card_matcher]]
