---
type: api-endpoint
method: POST
path: /gemini/identify
status: active
latency-p95: ~1-3s
source: src/api.py:1040-1168
related: [[../modules/gemini_identify]], [[identify-v2]]
area: [backend, api, recognition]
tags: [api, identification, gemini, llm]
created: 2026-05-21
updated: 2026-05-21
---

# POST /gemini/identify

> **TL;DR**: Альтернативный identify через Gemini Vision + Google Search. Медленнее (~1-3s) и стоит денег, но **не нужен local CLIP/OCR setup** и хорошо работает на edge cases.

## Request

| Param | In | Type | Default | Description |
|-------|-----|------|---------|-------------|
| `file` | body | UploadFile | — | Image |
| `use_search` | query | bool | True | Google Search для CardMarket URL + price (+ ~$0.035/call) |

## Response (`GeminiIdentifyResponse`)

```json
{
  "success": true,
  "processing_time_ms": 2140.5,
  "model_used": "gemini-2.0-flash-vision",
  "search_used": true,

  // From Gemini
  "card_name": "リザードンex",
  "card_name_english": "Charizard ex",
  "collector_number": "199",
  "set_name": "Stellar Crown",
  "set_abbreviation": "SCR",
  "language": "ja",
  "rarity": "SAR",
  "cardmarket_url": "https://www.cardmarket.com/...",  // from Gemini/Search
  "price_trend_eur": 12.50,
  "price_from_eur": 8.00,
  "confidence": 0.91,
  "notes": "...",

  // DB enrichment
  "cardmarket_url_db": "https://www.cardmarket.com/...",  // from local DB if matched
  "tcgdex_id": "sv07jp-199",
  "tcgplayer_url": "https://...",
  "pricecharting_url": "https://...",
  "price_usd": 14.30,
  "price_ebay_usd": 11.80,
  "graded_psa10": 250,
  "graded_psa9": 95,
  "graded_cgc10": 220,
  "has_graded": true,
  "price_avg": 9.50,
  "price_foil_trend": 0
}
```

## Pipeline

1. 503 if `_gemini_identifier` is None (нет `GEMINI_API_KEY`)
2. `_gemini_identifier.identify(contents, mime_type, use_search)`:
   - Gemini Vision → name, number, set, rarity, language
   - If `use_search=True`: Google Search находит CardMarket listing + price
3. **DB Enrichment** (`_enrich_gemini_from_db()`):
   - Strategy 1: number + set code
   - Strategy 2: number + total
   - Strategy 3: name search
   - Если multiple candidates: prefer name match, language priority JP > EN > TW
4. Если есть `tcgdex_id`: `_get_enriched_prices()` для TCGPlayer USD, eBay USD, graded
5. Return combined (Gemini + DB)

## Failure modes

- 503: `GEMINI_API_KEY` не задан
- DB enrichment **best-effort** — graceful если lookup failed
- Confidence threshold внутри Gemini: success если > 0.3

## Performance

| Mode | Latency | Cost (Gemini) |
|------|---------|---------------|
| `use_search=False` | ~1-2s | ~$0.005 |
| `use_search=True` | ~2-3s | ~$0.035 |

## Когда использовать

- **Use `/gemini/identify`** когда:
  - Карта damaged / необычная и `/identify-v2` провалился
  - Нужны Google Search results
  - На production fallback после `/identify-v2`
- **Use `/identify-v2`** в 95% случаев (быстрее, бесплатно).

## Связанные

- Module: [[../modules/gemini_identify]]
- Primary alternative: [[identify-v2]]
- Webapp использует cascade: `identifyCardSmart()` → v2 first → fallback to Gemini
