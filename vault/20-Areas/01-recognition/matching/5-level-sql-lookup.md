---
type: module
status: active
created: 2026-05-21
updated: 2026-05-21
area: [recognition, backend]
tags: [matching, sql, ocr]
related: [[../../06-api/modules/card_matcher]], [[../_MOC]], [[clip-faiss-fallback]]
source: src/card_matcher.py
---

# 5-Level SQL Lookup

> **TL;DR**: Strategy ladder для matching после OCR. От самого specific (number + set code) к самому broad (name only). Если все 5 levels fail → CLIP fallback.

## Алгоритм

```python
# Pseudocode из card_matcher.py
def match(image):
    ocr_result = ocr.extract(image)
    name = ocr_result.name
    number = ocr_result.collector_number  # e.g. "199/167"
    language = ocr_result.language        # 'en', 'ja', 'zh-tw'

    # L1: most specific — number + set code from OCR
    if number.set_code and number.number:
        matches = db.find(set_id_or_code=number.set_code,
                          collector_number=number.number,
                          language=language)
        if matches: return MatchResult(method="ocr_exact", confidence=0.95)

    # L2: number + total + language (no set code)
    if number.total and number.number:
        matches = db.find(collector_number=number.number,
                          set_total=number.total,
                          language=language)
        if matches: return narrow_by_name(matches, name)

    # L3: number + name fuzzy
    if number.number and name:
        matches = db.find(collector_number=number.number,
                          name_normalized=normalize(name),
                          language=language)
        if matches: return MatchResult(method="ocr_name", confidence=0.7-0.99)

    # L4: name only (broadest)
    if name:
        matches = db.find_fuzzy(name_normalized=normalize(name),
                                language=language,
                                threshold=75)
        if matches: return rerank_by_clip(matches, image)  # may go to L5

    # L5: CLIP fallback
    return clip_fallback(image)
```

## Confidence calibration

| Level | Method label | Confidence range |
|-------|-------------|------------------|
| L1 | `ocr_exact` | 0.95 |
| L2 | `ocr_number_match` | 0.80-0.95 |
| L3 | `ocr_name` | 0.7-0.99 (based on fuzzy score) |
| L4 | `ocr_name_fuzzy` | 0.5-0.85 |
| L5 | `clip_fallback` | 0.75 (visual only) |

## Indexes (для perf)

В `cards` table:
- `(set_id, number)` — для L1
- `(language, number, total)` — для L2
- `(language, name_normalized)` — для L3-L4

→ Все 5 levels работают <5ms суммарно при удачном match.

## Language tiebreaker

Когда multiple candidates с тем же именем:
1. Сначала filter по detected language
2. Если несколько остаются → priority **JP > EN > TW** (JP оригиналы)
3. Если всё ещё ambiguous → CLIP rerank по визуальной similarity

## Name normalization

См. `text_index.py:normalize_name()`:
- Remove brackets `[ability]`, parens `(NNN/MMM)`, parens `(notes)`
- Lowercase
- Remove spaces
- → `"Charizard ex [VMAX] (199/167)"` → `"charizardexvmax"`

## Fuzzy threshold

- L3/L4 fuzzy threshold: 75% similarity (rapidfuzz)
- Below → не возвращается из text_index

## Failure → CLIP fallback

Если все 5 levels не нашли — `clip_fallback`:
- Generate embedding
- FAISS L2 search top-K
- Dedup by `tcgdex_id`
- Return top match с confidence 0.75

См. [[clip-faiss-fallback]].

## Holographic OCR safety net

В `card_matcher.py:227-248`: для single candidate если fuzzy score < 55 → принудительно проверяем CLIP similarity (holographic carts иногда дают broken OCR text но визуально match).

## Связанные

- Module: [[../../06-api/modules/card_matcher]]
- Fallback: [[clip-faiss-fallback]]
- OCR: [[../ocr/_MOC|OCR engines]]
- Pipeline: [[../pipeline-overview]]
