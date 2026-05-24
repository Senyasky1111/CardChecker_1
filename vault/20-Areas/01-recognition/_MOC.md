---
type: moc
status: active
created: 2026-05-21
updated: 2026-05-23
area: [recognition, backend, ml]
tags: [moc, recognition]
---

# Recognition MOC

> Всё что нужно чтобы **опознать карту** по фотографии.
> Pipeline: фото → детекция → перспективная коррекция → OCR → 5-level SQL match → CLIP/FAISS fallback.

## Pipeline

- [[pipeline-overview]] — end-to-end схема

## Детекция

- [[detection/yolo-pose]] — primary detector (`models/card_detector.onnx`)
- Fallback: OpenCV contour detection — см. [[../06-api/modules/card_detector]]
- Training: [[../09-ml-research/yolo-card-detection/training]]
- Dataset: [[../09-ml-research/yolo-card-detection/dataset]]
- Benchmark: `scripts/benchmark_detectors.py` — см. [[../05-data-pipelines/scripts-catalog#Checks & Diagnostics (9)]]

## OCR

Engines: Tesseract (primary), EasyOCR, doctr.

- Module: [[../06-api/modules/ocr]]
- doctr-specific: [[../06-api/modules/doctr_detector]]
- ADR: [[../../30-Resources/adr/2026-05-23-tesseract-primary-easyocr-doctr-fallback]]
- Endpoint для number-only: [[../06-api/endpoints/detect-number]]

## Матчинг

- [[matching/5-level-sql-lookup]] — основной алгоритм (`src/card_matcher.py`)
- CLIP/FAISS fallback: see [[../09-ml-research/embedding-index/build-process]]
- ADR (CLIP uses warped image): [[../../30-Resources/adr/2026-05-23-clip-fallback-uses-warped-image]]
- Module: [[../06-api/modules/card_matcher]]
- Recent OCR cross-match work — коммит `1570a45` (см. log.md)

## Языки

EN / JP / TW. Coverage и source per language: [[../04-catalog/language-coverage]].

JP/TW OCR accuracy active project: [[../../10-Projects/2026-Q2-jp-tw-ocr-accuracy]].

ADR на JP > TW priority: [[../../30-Resources/adr/2026-05-23-jp-over-tw-language-priority]]

## Известные проблемы

(none currently logged — append к log.md когда возникают)

## Связанные

- API endpoint: [[../06-api/endpoints/identify-v2]]
- API endpoint: [[../06-api/endpoints/detect-card]]
- Catalog: [[../04-catalog/_MOC]]
- ML research: [[../09-ml-research/_MOC]]

## ADRs in this area

- [[../../30-Resources/adr/2026-05-23-yolo-pose-not-opencv-detection]]
- [[../../30-Resources/adr/2026-05-23-tesseract-primary-easyocr-doctr-fallback]]
- [[../../30-Resources/adr/2026-05-23-clip-fallback-uses-warped-image]]
- [[../../30-Resources/adr/2026-05-23-jp-over-tw-language-priority]]
