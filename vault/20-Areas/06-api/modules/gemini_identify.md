---
type: module
status: active
source: src/gemini_identify.py
lines: 292
related: [[../endpoints/gemini-identify]], [[gemini_grade]]
area: [backend, recognition, ml]
tags: [module, gemini, identification, llm]
created: 2026-05-21
updated: 2026-05-21
---

# gemini_identify.py

> **TL;DR**: Gemini Vision identification с optional Google Search grounding для CardMarket URL + price.

## Public surface

- `GeminiIdentifyResult` (dataclass) — `card_name`, `collector_number`, `set_name`, `set_abbreviation`, `language`, `rarity`, `cardmarket_url`, `price_trend_eur`, `price_from_eur`, `confidence`, `notes`
- `GeminiIdentifier`:
  - `identify(image_bytes, mime_type, use_search) → GeminiIdentifyResult`

## Два режима

| Mode | use_search | Latency | Cost | Gives |
|------|-----------|---------|------|-------|
| JSON-only | False | ~1-2s | ~$0.005 | Card name, number, set, rarity, language |
| Search-grounded | True | ~2-3s | ~$0.035 | Above + CardMarket URL + EUR price |

## Internal flow

1. Build content: image + instruction text
2. Call Gemini с system prompt (30 lines on card identification)
3. **Optional Google Search**: enable tool (temp=1.0 required, no JSON mode)
4. Parse JSON из response
5. Если `use_search=True`: extract CardMarket URL из grounding metadata

## Известный gotcha

- Line 188: `temperature=1.0` ОБЯЗАТЕЛЬНО когда use search (Google Search tool требует это, влияет на determinism)
- Line 202-216: `response.text` может быть `None` с search grounding → fallback на `candidates.content.parts` iteration

## Dependencies

- `google.genai` — `Client`, `types` (Part, `GenerateContentConfig`, `Tool`, `GoogleSearch`)
- `json`, `re`, `base64`

## Confidence threshold

- Internal: success если `confidence > 0.3`
- API endpoint потом enrich'ит DB lookup независимо от confidence

## Связанные

- API: [[../endpoints/gemini-identify]]
- Grading sibling: [[gemini_grade]]
- Use case: fallback для [[../endpoints/identify-v2]]
- Webapp использует cascade: `identifyCardSmart()` → v2 → Gemini
