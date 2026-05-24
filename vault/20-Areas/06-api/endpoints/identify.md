---
type: api-endpoint
method: POST
path: /identify
status: legacy
latency-p95: ~1-3s
source: src/api.py:262-326
related: [[../modules/recognizer]], [[identify-v2]]
area: [backend, api, recognition]
tags: [api, identification, clip, legacy]
created: 2026-05-21
updated: 2026-05-21
---

# POST /identify (legacy)

> **TL;DR**: Legacy endpoint на CLIP-эмбеддингах. Медленный (~1-3s). Оставлен для backward compat — для новой работы используй [[identify-v2]].

## Request

```http
POST /identify
Content-Type: multipart/form-data
```

| Param | In | Type | Default | Description |
|-------|-----|------|---------|-------------|
| `file` | body | UploadFile | — | Image |
| `k` | query | int (1-20) | 5 | top-K matches |
| `use_ocr` | query | bool | True | hybrid CLIP+OCR |
| `multi_crop` | query | bool | False | multi-crop voting fallback |
| `locale` | query | str | "en" | CardMarket locale |

## Response

```json
{
  "success": true,
  "processing_time_ms": 1240.5,
  "method": "hybrid",
  "top_match": { "id_product": 12345, "name": "...", "confidence": 0.87, ... },
  "alternatives": [ /* up to k-1 alternatives */ ],
  "ocr": { "name": "...", "collector_number": "199", "confidence": 0.92 }
}
```

## Pipeline (3 modes)

1. **If `use_ocr=True` (default)** — hybrid:
   - `_recognizer.identify_hybrid()` → OCR parse name/number + CLIP embedding match
   - Возвращает top-K + OCR metadata
   - Falls back to `identify_multi_crop()` на error

2. **Elif `multi_crop=True`** — multi-region voting:
   - `identify_multi_crop()` — много crop'ов, voting между предсказаниями

3. **Else** — pure CLIP:
   - `identify()` — single-shot embedding

## Failure modes

- 503: CLIP не загружен (`_recognizer` is None)
- 400: не image MIME
- OCR fail внутри hybrid → graceful fallback на multi_crop, print to stdout

## Performance

- `use_ocr=True`: 1-3s (медленнее, точнее)
- `multi_crop=True`: 500ms-2s
- `use_ocr=False, multi_crop=False`: ~500ms-1s

## Когда использовать вместо v2

- Когда нужно **CLIP-based recognition** конкретно (для рисёрча, бенчмарков)
- Когда OCR полностью провалился — CLIP может вытащить
- На очень damaged картах (OCR не читает, CLIP всё равно работает на artwork)

## Связанные

- Modern alternative: [[identify-v2]] (использовать его 99% времени)
- Module: [[../modules/recognizer]]
- Pipeline: [[../../01-recognition/_MOC]]
