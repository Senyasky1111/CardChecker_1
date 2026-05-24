---
type: adr
status: accepted
date: 2026-05-23
supersedes:
superseded-by:
area: [recognition, detection]
tags: [adr, yolo, opencv, detection]
---

# Use YOLO-pose for card detection, not OpenCV contours alone

## Context

Card detection (find card boundaries in photo + extract corners for perspective warp) initially used OpenCV contour detection. На clean studio backgrounds работало, но падало в реальных условиях:
- Карта на пёстром фоне (tabletop, sleeves, playmat)
- Частичное перекрытие пальцами
- Тени, отражения от glossy holo
- Карты на других картах (binder pages)

Перспективный warp требует **4 угла**, не bounding box. Нужны keypoints.

## Decision

**YOLO11-pose** с 4 keypoints (по одному на угол карты) как primary detector.
OpenCV contour-based detection (`src/card_detector.py`) сохранён как fallback для случаев когда YOLO confidence низкий или модель недоступна.

## Alternatives considered

- **Pure OpenCV (contours + Hough + heuristics)** — реализовано в `card_detector.py`. **Reject as primary**: brittle на сложных backgrounds, ~60-70% success rate на user photos.
- **Classic YOLO (bounding box)** — даёт прямоугольник, но не углы. Pose-вариант почти бесплатно сверху даёт keypoints.
- **Segment Anything (SAM)** — отличная маска, но 1) тяжёлая, 2) даёт mask, не углы (всё равно нужно contour fitting), 3) overkill для well-defined rectangles.
- **DETR / RT-DETR** — transformer-based detection. **Reject**: для одного класса (card) overkill, latency хуже YOLO.

## Consequences

### Positive

- **Robust** на реальных user photos: ~95% success rate
- **Углы напрямую** — keypoints maps to `cv2.getPerspectiveTransform()` без contour fitting
- **ONNX export** для inference — fast on CPU (~50ms), no PyTorch runtime in prod
- **Single model** для localization + corners
- OpenCV remains as fallback (zero extra dependencies)

### Negative / risks

- **Training data** требует annotation корнеров (не просто bounding box)
- **Model file size** ~10 MB (vs 0 for OpenCV)
- **Confidence threshold tuning** — нужен корректный cutoff чтобы fallback в OpenCV срабатывал когда надо

## Implementation

- Detector: `src/yolo_card_detector.py`
- ONNX export: `scripts/export_yolo_onnx.py`
- Training: `scripts/train_yolo_card.py`, `notebooks/train_card_detector.ipynb`
- Fallback: `src/card_detector.py`
- API integration: `/detect-card` endpoint в `src/api.py`

## Related

- [[../../20-Areas/01-recognition/detection/yolo-pose]]
- [[../../20-Areas/06-api/modules/yolo_card_detector]]
- [[../../20-Areas/06-api/modules/card_detector]]
