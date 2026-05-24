---
type: note
status: in-progress
area: [ml, grading]
tags: [yolo, defect-detection, training]
created: 2026-05-23
updated: 2026-05-23
---

# Defect YOLO — Training

> YOLOv11m обученная на TAG Grading dataset для defect localization.

## Цель

Дополнить Gemini-based grading explicit defect detector. Gemini даёт holistic grade + qualitative defects, но:
- Не предсказывает точную локализацию (bbox) defect'а
- Subject to LLM hallucination для borderline cases
- Дороже / медленнее чем dedicated CV model

YOLO defect detector предоставит **fast deterministic CV layer** который supplements (не замещает) Gemini grading. Связан с [[../../../10-Projects/2026-Q2-opencv-defects]].

## Dataset

**TAG Grading reports** — scraped через `scripts/scrape_tag.py` (~1472 строк, наш самый большой scraper). См. также [[../../05-data-pipelines/tag-scraping/overview]].

Volumes:
- **23,116 images** total
- **57,614 defect annotations**
- **7 classes**:
  - `corner_wear` (41%)
  - `surface_damage` (23%)
  - `edge_wear` (19%)
  - `crease` (6%)
  - `scratch` (5%)
  - `dent` (5%)
  - `stain` (0.5%)

Class imbalance: `stain` extreme rare → over-sampling или class weights нужны.

## Training script

`scripts/train_defect_yolo.py` (~296 строк):
- **Model**: YOLOv11m (medium — balance accuracy / inference cost)
- **Image size**: 640
- **Batch**: 16 (fit на RTX 4060 8GB)
- **Epochs**: 100
- **Augmentation**: tuned for cards
  - No vertical flip
  - Slight rotation (±5°) — cards have orientation
  - Mosaic enabled
  - Mixup disabled (would混淆 defect localization)

## Notebook

`notebooks/train_defect_detector.ipynb` — interactive workflow с rich visualizations:
- Defect heatmaps (where в карты обычно defects)
- Per-class bbox size distribution
- Ground truth vs prediction side-by-side
- Confusion matrix
- Per-class PR / F1 curves

## Output

- `runs/defect/train_v2/weights/best.pt`
- ONNX export для production inference

## Inference

For grading API:
1. Run defect YOLO on warped card image
2. Per detected defect: class + bbox + confidence
3. Convert to severity: LOW (small / low-conf), MEDIUM, HIGH (large / multiple) — heuristic
4. Convert bbox center to location label (`top`, `bottom`, `left`, `right`, `center`)
5. Return alongside Gemini grade для consolidated response

Integration point: `/gemini/grade` enhancement — defect list comes from YOLO, not Gemini, более точная локализация.

## Status (2026-05-23)

**In-progress** — model trains acceptable, но not yet integrated в production grading endpoint. Active milestone в [[../../../10-Projects/2026-Q2-opencv-defects]].

Pending:
- [ ] Confidence threshold calibration per class
- [ ] Integration в `/gemini/grade` response
- [ ] Mobile heatmap UI updated for YOLO output format
- [ ] Cleanup `stain` class (rare → unstable predictions)

## Related

- [[../../02-grading/_MOC]]
- [[../../02-grading/defect-detection/architecture]]
- [[../../05-data-pipelines/tag-scraping/overview]]
- [[../../../10-Projects/2026-Q2-opencv-defects]]
