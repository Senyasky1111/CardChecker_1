---
type: moc
status: active
created: 2026-05-21
updated: 2026-05-23
area: [ml]
tags: [moc, training, experiments]
---

# ML Research MOC

> Обучение моделей, эксперименты, бенчмарки.
> Здесь живёт всё что **не в проде** — рисёрч, training runs, неудачные попытки.

## YOLO Card Detection (production)

- [[yolo-card-detection/training]] — `scripts/train_yolo_card.py`, YOLOv8n-pose
- [[yolo-card-detection/dataset]] — synthetic compositing pipeline (`scripts/generate_yolo_dataset.py`)

Production inference: [[../06-api/modules/yolo_card_detector]] (ONNX, CPU).

## CLIP Fine-tuning (experimental)

- [[clip-finetuning/strategy]] — what, why, status
- [[clip-finetuning/pairs-generation]] — `scripts/generate_training_pairs.py`

Production currently uses pretrained CLIP. Fine-tuned weights pending validation.

## Defect YOLO (in-progress)

- [[defect-yolo/training]] — YOLOv11m на TAG dataset (23K images, 7 defect classes)

Active milestone в [[../../10-Projects/2026-Q2-opencv-defects]].

## Embedding Index (production)

- [[embedding-index/build-process]] — FAISS, 50K cards × 768-dim CLIP embeddings

## Лог экспериментов

- [[experiments-log]] — append-only журнал. **Update every run.**

## Связанные

- Recognition: [[../01-recognition/_MOC]]
- Defect detection architecture: [[../02-grading/defect-detection/architecture]]
- Project: [[../../10-Projects/2026-Q2-opencv-defects]]

## ADRs in this area

- [[../../30-Resources/adr/2026-05-23-yolo-pose-not-opencv-detection]]
- [[../../30-Resources/adr/2026-05-23-tesseract-primary-easyocr-doctr-fallback]]
- [[../../30-Resources/adr/2026-05-23-clip-fallback-uses-warped-image]]
