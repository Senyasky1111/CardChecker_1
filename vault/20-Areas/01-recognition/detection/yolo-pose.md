---
type: module
status: active
created: 2026-05-21
updated: 2026-05-21
area: [recognition, detection, ml]
tags: [detection, yolo, onnx, keypoints]
related: [[../../06-api/modules/yolo_card_detector]], [[opencv-contours]], [[perspective-warp]]
source: src/yolo_card_detector.py
---

# YOLO-pose Detection

> **TL;DR**: Current default detector. YOLO-pose model predicts 4 corner keypoints (TL/TR/BR/BL) directly. CPU ONNX ~50-100ms.

## Что делает

Вход: PIL Image (любого размера и aspect ratio)
Выход: 4 точки углов карты в координатах исходного image + confidence

## Почему именно pose-style (а не bbox)

- bbox даёт прямоугольник, **выровненный по осям** — на angled photo это плохо
- pose keypoints дают **точные corner positions** — карта может быть под любым углом
- → лучше для perspective correction

## Model

| Поле | Значение |
|------|----------|
| File | `models/card_detector.onnx` |
| Input | `[1, 3, 640, 640]` float32 normalized (0-1) |
| Output | bbox + 4 keypoints × (x, y, visibility) |
| Trained on | `data/yolo_card_dataset/` |
| Confidence threshold | 0.3 |
| Keypoint conf threshold | 0.2 |

## Preprocessing

1. **Letterbox** — scale + pad to 640×640 (preserve aspect ratio)
2. Normalize 0-1
3. NCHW batch tensor

## Postprocessing

1. Parse output `(N, 18)` или `(18, N)` (handle both transpositions)
2. Filter by confidence
3. Validate keypoint visibility — нужно ≥3 visible corners
4. Fallback: если <3 keypoints visible → use bbox corners (confidence × 0.5)
5. Unmap из letterbox обратно в original coords
6. Expand corners 2% наружу — иначе collector number строка обрезается

## Производительность

| Provider | Latency |
|----------|---------|
| CPU (ONNX Runtime) | ~50-100ms |
| CUDA (если доступно) | ~10-20ms |

`onnxruntime.get_available_providers()` определяет automatically.

## Когда не работает

- Карта в **очень damaged sleeve** — keypoints скрыты → fallback к [[doctr-detection]] (text-based)
- **Extreme angle** (>45°) — keypoints invisible → fallback к OpenCV contours
- Слишком маленькая (<200px ширина) — нужен closer crop

## Training

См. [[../../09-ml-research/yolo-card-detection/training]] — `scripts/train_yolo_card.py`.

Dataset: `data/yolo_card_dataset/`
- ~5000 labeled cards (front + back, разные углы)
- Augmentations: rotation, brightness, occlusion

## Связанные

- Module: [[../../06-api/modules/yolo_card_detector]]
- Fallback: [[opencv-contours]]
- Special case: [[../../06-api/modules/doctr_detector]] для sleeves
- Training: [[../../09-ml-research/yolo-card-detection/_MOC|YOLO training]]
- Comparison: [[benchmark-comparison]]
