---
type: module
status: active
source: src/yolo_card_detector.py
lines: 405
related: [[card_detector]], [[../../09-ml-research/yolo-card-detection/training]]
area: [backend, detection, ml]
tags: [module, detection, yolo, onnx]
created: 2026-05-21
updated: 2026-05-21
---

# yolo_card_detector.py

> **TL;DR**: YOLO-pose card detector через ONNX Runtime. Предсказывает 4 corner keypoints (TL/TR/BR/BL) напрямую. **Default backend** для prod.

## Public surface

- `YOLOCardDetector` — ONNX-based class
  - `detect(image) → DetectionResult`
  - Constants: `INPUT_SIZE=640`, `CONF_THRESHOLD=0.3`, `KPT_CONF_THRESHOLD=0.2`

## Internal flow

1. **Letterbox preprocessing** — scale + pad to 640×640, normalize 0-1, NCHW batch
2. **ONNX inference** — parse output shape `(N, 18)` или `(18, N)`
3. Extract bbox (center, w, h) + 4 keypoints (x, y, visibility)
4. Filter by confidence
5. Validate keypoint visibility — need ≥3 visible corners
6. **Fallback** to bbox corners если keypoints <3 visible (confidence × 0.5)
7. **Unmap** coords из letterbox обратно в original image
8. Expand corners наружу 2% — чтобы не обрезать collector-number полосу
9. Warp to 600×825

## Model

- File: `models/card_detector.onnx`
- Input: `[1, 3, 640, 640]` float32 normalized
- Output keypoints: 4 углов в порядке TL, TR, BR, BL
- Trained on `data/yolo_card_dataset/`

## Dependencies

- `onnxruntime` (CUDA opt'l, falls back to CPU)
- `src.card_detector` — `DetectionResult`, `check_passthrough()`, `order_corners()`, `warp_card()`, `visualize_detection()`
- `cv2`, `PIL`, `numpy`

## Notable patterns

- **CUDA-optional**: checks `available_providers`, fallback на CPU
- **Output format flexibility**: handles `(N, 18)` и `(18, N)` transpositions
- **Letterbox math**: scale + pixel padding offsets preserved для unmapping

## Производительность

- CPU ONNX: ~50-100ms
- CUDA (если доступно): ~10-20ms

## Связанные

- OpenCV fallback: [[card_detector]]
- Training: [[../../09-ml-research/yolo-card-detection/training]]
- Detection method: [[../../01-recognition/detection/yolo-pose]]
