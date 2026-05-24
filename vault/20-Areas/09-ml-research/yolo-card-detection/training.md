---
type: note
status: stable
area: [ml, detection]
tags: [yolo, training, card-detection]
created: 2026-05-23
updated: 2026-05-23
---

# YOLO Card Detection — Training

> YOLOv8n-pose обученная на synthetic dataset для bounding box + 4 corner keypoints карты.

## Что делает

Detector предсказывает per-image:
- Card bounding box (single class: `card`)
- 4 keypoints в порядке: top-left, top-right, bottom-right, bottom-left

Корнеры используются прямо в `cv2.getPerspectiveTransform()` для warp в canonical orientation.

## Training script

`scripts/train_yolo_card.py` (~131 строк) — обёртка вокруг ultralytics `YOLO('yolov8n-pose.yaml').train(...)`.

Дефолтные параметры:
- **Model**: YOLOv8n-pose (smallest, ~3.5M params)
- **Image size**: 640
- **Batch**: 16
- **Epochs**: 100
- **Optimizer**: SGD with auto lr
- **Augmentation**: ultralytics defaults + наш custom synthetic generation (см. [[dataset]])

## Dataset

См. [[dataset]]. Composite из чистых scans + procedural backgrounds через `scripts/generate_yolo_dataset.py`.

## Output

- `runs/pose/card_detector/weights/best.pt` — PyTorch checkpoint
- ONNX export через `scripts/export_yolo_onnx.py` → `models/yolo_card.onnx`
- Inference в проде: `src/yolo_card_detector.py` (ONNX runtime, CPU, ~50ms)

## Notebook

`notebooks/train_card_detector.ipynb` — interactive variant (recommended для Colab T4). Workflow:
1. Upload zipped dataset
2. Unzip + verify
3. Train (100 epochs, ~1-2h на T4)
4. Validate on holdout
5. Export ONNX
6. Download artefacts

## Metrics (reference)

Best run так-сяк зафиксирован — добавлять в [[../experiments-log]] при каждом training run:
- box mAP50 ≈ 0.99 (card detection trivial — single class)
- keypoint OKS ≈ 0.95 на holdout
- Real-world precision на user photos ≈ 95% (estimate)

## When to retrain

- Если меняем canonical resolution warp output
- Если добавляем новые user photo patterns которые current model fails (e.g. very dark / very glossy backgrounds)
- Если меняем backbone (YOLOv8n → YOLOv11n) — может дать accuracy bump

## Related

- [[dataset]]
- [[../../06-api/modules/yolo_card_detector]]
- [[../../30-Resources/adr/2026-05-23-yolo-pose-not-opencv-detection|ADR: YOLO-pose primary detector]]
