---
type: api-endpoint
method: POST
path: /identify-v2
status: preferred
latency-p95: ~100ms
source: src/api.py:609-653
related: [[../modules/card_matcher]], [[../_MOC]], [[../../01-recognition/_MOC]]
area: [backend, api, recognition]
tags: [api, identification, preferred]
created: 2026-05-21
updated: 2026-05-21
---

# POST /identify-v2

> **TL;DR**: Preferred endpoint для опознавания карт. OCR + SQL match, без CLIP. ~100ms vs ~1-3s у legacy `/identify`.
> Mobile + webapp используют именно его.

## Request

```http
POST /identify-v2
Content-Type: multipart/form-data
```

| Param | In | Type | Required | Description |
|-------|-----|------|----------|-------------|
| `file` | body | UploadFile | ✅ | Image (any common format) |
| `locale` | query | str | ❌ | CardMarket locale (default "en") |

## Response

```json
{
  "success": true,
  "processing_time_ms": 87.4,
  "method": "ocr_exact",
  "ocr_name": "Charizard ex",
  "ocr_number": "199",
  "detected_language": "en",
  "confidence": 0.92,
  "top_match": { /* SQLCardMatch */ },
  "alternatives": [ /* up to 4 alternative matches */ ]
}
```

### `SQLCardMatch` fields

| Field | Type | Source |
|-------|------|--------|
| `tcgdex_id` | str | DB primary key |
| `name`, `eng_name`, `language`, `set_name`, `set_id`, `abbreviation`, `collector_number`, `set_total`, `rarity` | mixed | DB `cards` table |
| `cm_id_product`, `price_trend`, `price_low`, `price_avg`, `price_foil_trend` | mixed | CardMarket (EUR) |
| `image_url`, `cardmarket_url`, `tcgplayer_url`, `pricecharting_url`, `ebay_url` | str | Generated/stored |
| `tcgplayer_id` | int | DB |
| `price_usd`, `price_ebay_usd` | float | `prices_external` (USD) |
| `graded_psa10`, `graded_psa9`, `graded_cgc10`, `has_graded` | mixed | `prices_external` |

## Pipeline

1. Read image bytes → PIL RGB
2. `_matcher.match(image)` — **pure OCR**:
   - Extract name + collector number via OCR
   - 5-level SQL lookup в `cards` table (sub-ms)
   - Return best + up to 4 alternatives
3. For each match: `_match_to_card()` → enrich:
   - Build CardMarket URL via `cardmarket_url()` module
   - Build TCGPlayer URL (stored or fallback)
   - Build PriceCharting URL (stored or generated)
   - Build eBay sold URL
   - Fetch enriched prices from `prices_external`

## Method values

- `ocr_exact` — точное совпадение по имени + номеру
- `ocr_name` — match только по имени
- `ocr_number` — match только по номеру

## Failure modes

| Code | When |
|------|------|
| 503 | `_matcher` не загружен (нет `data/cards.db`) |
| 400 | Не image MIME type |
| 422 | Ошибки валидации |

Если OCR не находит ничего → `success: false`, пустые `top_match` и `alternatives`.

## Performance

- Typical: 50-100ms
- p95: ~100ms
- Bottleneck: OCR (Tesseract/EasyOCR ~50-80ms), SQL match <1ms

## Recent changes

- 2026-04+ — добавлен `ocr_number` метод как primary для JP/TW (где name OCR хуже)
- 2026-05 (1570a45) — OCR cross-match для CLIP fallback

## Связанные

- Module: [[../modules/card_matcher]]
- Pipeline overview: [[../../01-recognition/pipeline-overview]]
- JP/TW accuracy project: [[../../../10-Projects/2026-Q2-jp-tw-ocr-accuracy]]
- Legacy alternative: [[identify]]
- Gemini alternative: [[gemini-identify]]
