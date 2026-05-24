---
type: api-endpoint
method: POST
path: /detect-number
status: active
latency-p95: ~100-500ms
source: src/api.py:329-405
related: [[../modules/ocr]], [[../../01-recognition/ocr/number-extraction]]
area: [backend, api, ocr]
tags: [api, ocr, collector-number]
created: 2026-05-21
updated: 2026-05-21
---

# POST /detect-number

> **TL;DR**: Чисто OCR — извлекает collector number ("45/120") из фото карты. Useful для testing OCR и для use case'ов где имя не нужно.

## Request

| Param | In | Type | Default | Description |
|-------|-----|------|---------|-------------|
| `file` | body | UploadFile | — | Image |
| `debug` | query | bool | False | Включить per-band OCR details |

## Response

```json
{
  "success": true,
  "number": "45/120",
  "card_number": 45,
  "total": 120,
  "set_code": "SSP",
  "raw_ocr": "45/120 SSP",
  "confidence": 0.91,
  "processing_time_ms": 184.2,
  "debug": null
}
```

### Debug mode (`debug=true`)

```json
{
  ...,
  "debug": {
    "card_detected": true,
    "bands": [
      {
        "band": 0,
        "region": [0, 750, 600, 825],
        "texts": [["45/120", 0.91], ["SSP", 0.87]],
        "joined": "45/120 SSP"
      },
      ...
    ]
  }
}
```

## Pipeline

1. Read image → RGB
2. `CardOCR()` instance
3. `_detect_card_boundary()` → 4 corners
4. If corners found: `_perspective_correct()` to 600×825
5. Else: resize fallback
6. `_extract_collector_number(card_img)` → `(CollectorNumber | None, confidence)`
7. If `debug=True`: re-run band-by-band, 4× upscale, EasyOCR per band

## Failure modes

- 400: не image MIME
- `success: false` если OCR не извлёк ничего узнаваемого

## Performance

- Typical: 100-200ms
- Debug mode: 300-500ms (re-runs OCR per band)
- Bottleneck: EasyOCR на bands

## Use cases

- Testing OCR при отладке
- Re-identification по номеру (если в кеше есть карта но фото изменилось)
- Verification что номер виден на конкретной карте

## Связанные

- Module: [[../modules/ocr]]
- Number extraction: [[../../01-recognition/ocr/number-extraction]]
- Full identification: [[identify-v2]]
