---
type: api-endpoint
method: GET
path: /health
status: active
latency-p95: <1ms
source: src/api.py:242-259
related: [[../_MOC]], [[../modules/db]]
area: [backend, api]
tags: [api, health, diagnostics]
created: 2026-05-21
updated: 2026-05-21
---

# GET /health

> **TL;DR**: Health check + статистика — сколько карт в индексе CLIP, в БД, разбивка по языкам, какая модель CLIP загружена.

## Request

```http
GET /health
```

Без параметров.

## Response

```json
{
  "status": "healthy",
  "cards_indexed": 15234,
  "cards_in_db": 48497,
  "cards_by_language": {
    "en": 22000,
    "ja": 15000,
    "zh-tw": 12000
  },
  "model": "openai/clip-vit-base-patch32"
}
```

## Pipeline

1. Читает state из `_recognizer.card_ids` (если CLIP загружен)
2. Читает `_matcher.card_count` (если БД загружена)
3. SQL: `SELECT language, COUNT(*) FROM cards GROUP BY language`
4. Возвращает agg

## Failure modes

- Никаких — graceful return даже если `_recognizer` или `_matcher` = None (0 и пустой dict)

## Performance

- Typical: <1ms
- No file I/O, no external calls

## Связанные

- DB module: [[../modules/db]]
- Used by: monitoring, mobile app (для health check)
