---
type: module
status: active
source: src/doctr_detector.py
lines: 120
related: [[card_detector]], [[../../01-recognition/ocr/doctr]]
area: [backend, detection, ml]
tags: [module, detection, doctr, text-localization]
created: 2026-05-21
updated: 2026-05-21
---

# doctr_detector.py

> **TL;DR**: DocTR-based detector — использует pretrained DBNet text localization. **Robust на sleeved/angled cards** где YOLO может промахнуться, потому что детектит text regions, не corners.

## Public surface

- `DocTRCardDetector` — initialized с DocTR arch (default `"db_resnet50"`)
  - `detect(image) → DetectionResult`

## Internal flow

1. DocTR text detection на RGB image (expects [0,1] float)
2. Collect all text box corners (normalized → pixel coords)
3. Convex hull всех точек → `minAreaRect` → 4 corners
4. Expand slightly (×1.05) — текст внутри border
5. Clip to image bounds
6. Warp to 600×825

## Когда полезен

- Карта в sleeve или капсуле — YOLO видит sleeve corners, DocTR видит реальный card text
- Угловой ракурс — YOLO может потерять corners, text всё ещё виден
- Backup для damaged corners

## Dependencies

- `doctr.models` — `detection_predictor(pretrained=True)`
- `src.card_detector` — constants, `DetectionResult`, `check_passthrough()`, `order_corners()`, `warp_card()`
- `cv2`, `PIL`, `numpy`
- Сетит `USE_TORCH=1` env var

## Threshold

- Требует ≥3 text regions (low bar для cards с минимумом текста)

## Confidence

- = средний confidence всех text detections (0-1)

## Используется в

- `card_matcher.py` — fallback после YOLO когда OCR number не найден
- Можно вызвать напрямую через `/detect-card?backend=doctr`

## Связанные

- OpenCV: [[card_detector]]
- YOLO: [[yolo_card_detector]]
- OCR doctr: [[../../01-recognition/ocr/doctr]]
- В pipeline matching: [[card_matcher]]
