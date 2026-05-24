---
type: moc
status: active
created: 2026-05-21
updated: 2026-05-23
area: [grading, ml]
tags: [moc, grading, psa]
---

# Grading MOC

> Оценка **состояния карты** в PSA-style шкале 1-10.
> Сегодня: Gemini 2.5 Flash на 4 столпах (centering/corners/edges/surface), вес front 65% / back 35%.
> Roadmap: дополнить explicit YOLO defect detector.

## Базовая модель

- **4 pillars**: centering, corners, edges, surface (PSA-style)
- **Per-side grading**: front + optional back
- **Weighting**: front 65% / back 35% → see [[../../30-Resources/adr/2026-05-23-grade-weights-front-65-back-35|ADR]]
- **Output scale**: 1.0–10.0, PSA-aligned interpretation

## Gemini Vision (current implementation)

- Module: [[../06-api/modules/gemini_grade]]
- Endpoint: [[../06-api/endpoints/gemini-grade]]
- Identification fallback (separate flow): [[../06-api/modules/gemini_identify]]

## Defect Detection (in-progress)

- [[defect-detection/architecture]] — server GPU layer, multi-angle, YOLO
- Training pipeline: [[../09-ml-research/defect-yolo/training]]
- Source dataset: [[../05-data-pipelines/tag-scraping/overview]] (TAG grading reports)
- Active project: [[../../10-Projects/2026-Q2-opencv-defects]]

## Industry context

Конкуренты и rubrics:
- PSA — primary benchmark
- BGS — alternative
- TAG — наш data source (см. [[../05-data-pipelines/tag-scraping/overview]])

(detailed competitor analyses не написаны — добавим если понадобится для product strategy)

## Связанные

- API: [[../06-api/endpoints/gemini-grade]]
- Data pipeline (TAG): [[../05-data-pipelines/tag-scraping/overview]]
- ML research: [[../09-ml-research/defect-yolo/training]]
- Mobile UI: [[../07-mobile/components-overview#Grading domain]]

## ADRs in this area

- [[../../30-Resources/adr/2026-05-23-grade-weights-front-65-back-35]]
- [[../../30-Resources/adr/2026-03-21-gemini-for-grading-not-custom-model]]
