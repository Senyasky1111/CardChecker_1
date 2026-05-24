---
type: api-endpoint
method: POST
path: /detect-card
status: active
latency-p95: ~50-200ms
source: src/api.py:545-606
related: [[../modules/card_detector]], [[../modules/yolo_card_detector]], [[../../01-recognition/detection/yolo-pose]]
area: [backend, api, detection]
tags: [api, detection, opencv, yolo]
created: 2026-05-21
updated: 2026-05-21
---

# POST /detect-card

> **TL;DR**: Детектит границы карты на фото и делает perspective correction (warps в 600×825). Возвращает corners + URL'ы annotated/warped image для дебага.

## Request

```http
POST /detect-card
Content-Type: multipart/form-data
```

| Param | In | Type | Default | Description |
|-------|-----|------|---------|-------------|
| `file` | body | UploadFile | — | Image |
| `visualize` | query | bool | True | Save annotated + warped images to `/static/` |
| `backend` | query | str | "auto" | `"auto"`, `"yolo"`, or `"opencv"` |

## Response

```json
{
  "card_found": true,
  "method": "contour",            // or "hough", "fallback"
  "confidence": 0.9234,
  "corners": [[120, 50], [580, 60], [575, 690], [115, 680]],
  "processing_time_ms": 87.3,
  "backend": "YOLOCardDetector",
  "annotated_url": "/static/detect_abc123_annotated.jpg",
  "warped_url": "/static/detect_abc123_warped.jpg"
}
```

## Pipeline

1. Read image → PIL RGB
2. Select detector:
   - `backend="auto"` → global `_detector` (auto-initialized at startup, YOLO с fallback на OpenCV)
   - else → `get_detector(backend)` on-demand
3. `detector.detect(image)` → `DetectionResult` (corners, confidence, method)
4. **If `visualize=True`**:
   - MD5 hash первых 1KB файла → unique filename `abc123`
   - `visualize_detection(image, result)` → annotated PIL
   - Save to `static/detect_{hash}_annotated.jpg`
   - If warped available → `static/detect_{hash}_warped.jpg`

## Method values

- `contour` — OpenCV contour detection (default OpenCV)
- `hough` — Hough line detection (OpenCV fallback)
- `fallback` — Не нашёл карту, использует весь image как есть

## Failure modes

- 400: Backend не доступен
- Если карта не найдена: `card_found: false`, corners = весь image rectangle

## Performance

| Backend | Latency |
|---------|---------|
| YOLO (CPU ONNX) | ~50-100ms |
| OpenCV contour | ~100-200ms |
| OpenCV Hough fallback | ~200-300ms |

## Output для downstream

- **Annotated image** — для UI визуализации (mobile/webapp показывают bbox)
- **Warped image** — нормализованный 600×825 crop для последующих identify/grade endpoints

## Связанные

- Modules: [[../modules/card_detector]], [[../modules/yolo_card_detector]]
- Detection methods: [[../../01-recognition/detection/yolo-pose]], [[../../01-recognition/detection/opencv-contours]]
- Perspective warp: [[../../01-recognition/detection/perspective-warp]]
- Benchmark: [[../../01-recognition/detection/benchmark-comparison]]
