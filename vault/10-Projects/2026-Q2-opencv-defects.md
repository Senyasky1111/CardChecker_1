---
type: project
status: in-progress
created: 2026-05-21
updated: 2026-05-24
priority: 2
target: 2026-Q2
area: [grading, ml]
tags: [defect-detection, opencv, q2]
related: [[../20-Areas/02-grading/defect-detection/architecture]], [[../20-Areas/02-grading/gemini-model-upgrade]]
---

# Project: OpenCV Defect Detection Layer

> **Priority #2** (demoted 2026-05-24 — Mobile Auth promoted to #1 as tech debt). Дополнить Gemini grading быстрым OpenCV-слоем для defect detection.

## Interim improvement (parallel track)

Пока YOLO defect detector не готов (Phases 3-4 ниже), рассмотреть **upgrade Gemini Flash → stronger model** для grading endpoint. См. [[../20-Areas/02-grading/gemini-model-upgrade]] — options + tradeoffs.

## Goal

Создать **fast OpenCV pipeline** который ловит:
- Centering (deterministic Sobel + border detection)
- Image Quality Gate (blur, lighting check перед grading)
- Базовые structural defects (где OpenCV хорош)

Чтобы Gemini вызывался **только когда нужно**, не на каждую карту.

## Why

- Gemini latency: 3-5s + cost per call
- 80% карт можно отгрейдить чисто OpenCV (centering + obvious defects)
- Gemini зарезервировать на edge cases + final verification

## Phases

### Phase 1: Image Quality Gate
- [ ] Blur detection (Laplacian variance)
- [ ] Lighting check (histogram analysis)
- [ ] Card occlusion check
- [ ] Перформанс target: <100ms

### Phase 2: OpenCV Centering
- [ ] Sobel edge detection
- [ ] Border localization
- [ ] L/R, T/B ratios
- [ ] Validate vs TAG centering ground truth
- [ ] Target: ±2% accuracy

### Phase 3: TAG data → defect annotation
- [ ] Reverse-engineer TAG SPA API (DevTools → endpoints)
- [ ] Парсить DINGS из metadata
- [ ] Gemini-assisted bbox annotation на TAG photos

### Phase 4: YOLO26x-OBB training
- [ ] Подготовить dataset из TAG + аннотаций
- [ ] Train + evaluate
- [ ] GPU инфраструктура (Arsenii buys GPU for Hetzner)

## Done means

- Centering работает локально с точностью ±2% от TAG ground truth
- Image quality gate отсекает плохие фото до Gemini
- Pipeline решает: OpenCV-only / Gemini / ensemble — based на confidence

## Risk

- TAG data — нет pixel-level coords, требует Gemini-assisted annotation pipeline
- GPU стоимость + setup

## Architecture

См. [[../20-Areas/02-grading/defect-detection/architecture]] — 8 решений принято 2026-03-21.

## Связанные

- Architecture: [[../20-Areas/02-grading/defect-detection/architecture]]
- TAG data: [[../20-Areas/05-data-pipelines/tag-scraping/overview]]
- ML training: [[../20-Areas/09-ml-research/defect-yolo/strategy]]
- Skill: `/defect-grader`
