---
type: context-pack
status: active
created: 2026-05-21
updated: 2026-05-21
tags: [context-pack, defect-detection]
---

# Context Pack: Working on Defect Detection

> **Use when**: Работаешь над defect detection — OpenCV layer, YOLO training, TAG data, calibration.
> **Tell Claude**: "Read `_context-packs/working-on-defect-detection.md` first."

## Core decisions

![[../20-Areas/02-grading/defect-detection/architecture]]

## Where TAG data comes from

![[../20-Areas/05-data-pipelines/tag-scraping/overview]]

## Known issues with TAG data

- См. [[../20-Areas/05-data-pipelines/tag-scraping/cdn-migration-cloudfront]] — почему ~19.8K cards нужны re-scrape

## Project & current focus

- [[../10-Projects/2026-Q2-opencv-defects]]

## Code locations

- `src/gemini_grade.py` — текущий Gemini grading
- `scripts/scrape_tag.py` — TAG data pipeline
- `scripts/train_defect_yolo.py` — YOLO training (план)
- `scripts/generate_training_pairs.py` — синтетические дефекты

## Skill

Если глубокий рисёрч по defect detection — `/defect-grader`.
Если general CV/ML — `/cv-expert`.

## Data available

- `data/tag_raw/` — 96,551 cert (423 GB)
- `data/tag_dataset/` — 96 GB processed YOLO format
- `data/tag_dataset_1280/` — 11 GB resized version
- `data/scraper.db` — 115K cards в state DB

## Что НЕ делать

- НЕ переобучаться на 12 defect классов сразу — начни с базовых (corner_whitening, edge_chip)
- НЕ полагаться только на synthetic — нужны real-world ракурсы
- НЕ выкидывать calibration validation — это блокер прода
