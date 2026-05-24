---
type: context-pack
status: active
created: 2026-05-21
updated: 2026-05-21
tags: [context-pack, recognition, ocr]
---

# Context Pack: Working on Recognition

> **Use when**: Работаешь над identification pipeline — детекция, OCR, SQL match, CLIP fallback.

## Recognition pipeline overview

![[../20-Areas/01-recognition/_MOC]]

## API endpoints involved

![[../20-Areas/06-api/_MOC]]

## Active project (JP/TW accuracy)

- [[../10-Projects/2026-Q2-jp-tw-ocr-accuracy]]

## Code

- `src/api.py` — endpoints `/identify-v2`, `/identify`, `/detect-card`, `/detect-number`
- `src/card_matcher.py` — 5-level SQL lookup + CLIP fallback
- `src/card_detector.py` — OpenCV detection
- `src/yolo_card_detector.py` — YOLO детекция
- `src/doctr_detector.py` — doctr OCR (новый)
- `src/ocr.py` — Tesseract/EasyOCR
- `src/recognizer.py` — CLIP-based (legacy fallback)
- `src/text_index.py` — text search

## Models on disk

- `models/card_detector.onnx` — YOLO card detection
- `models/card_index/cards.faiss` — FAISS embedding index
- `models/card_index/metadata.pkl` — index metadata
- `models/card_index/cards_indexed.json`

## Skill

`/card-engine` для глубокого dive в recognition + pricing.
`/cv-expert` для CV/ML research.

## Что важно

- `/identify-v2` — preferred (~100ms), на нём строится mobile + webapp
- `/identify` — legacy CLIP, оставлен для compat
- JP/TW OCR — известная слабость, см. project
- CLIP fallback срабатывает при confidence < 0.5

## Improvements в свежем коде (1570a45)

- OCR cross-match (новая фича)
- Detection fixes
- Improved CLIP fallback
