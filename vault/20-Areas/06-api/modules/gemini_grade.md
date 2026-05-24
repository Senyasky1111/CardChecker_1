---
type: module
status: active
source: src/gemini_grade.py
lines: 458
related: [[../endpoints/gemini-grade]], [[../../02-grading/_MOC]]
area: [backend, grading, ml]
tags: [module, gemini, grading, psa]
created: 2026-05-21
updated: 2026-05-21
---

# gemini_grade.py

> **TL;DR**: Gemini Vision PSA-style grading. 4 столпа (centering/corners/edges/surface), front/back separately, 60+ lines of anti-hallucination правил в system prompt.

## Public surface

### Dataclasses

- `GeminiGradeResult` — `overall_grade`, `grade_label`, front/back grades, pillar scores, `key_defects`, `explanation`, `grade_probabilities`, `image_quality_warning`
- `SideGrade` — per-side (front/back): grade + 4 pillars
- `PillarScore` — `score`, `notes`, `lr` (centering), `tb` (centering)
- `Defect` — `side`, `location`, `type`, `severity`, `visibility`

### Main class

- `GeminiGrader`:
  - `grade(front_bytes, back_bytes, mime_type) → GeminiGradeResult`

## Internal flow

1. Build image parts: front + optional back + instruction text
2. Call Gemini 2.5 Flash с system prompt (70+ lines calibration rules)
3. Parse JSON response: front/back sides, pillar scores (9.5-10 / 9.0 / 8.0-8.5 / etc.)
4. Combine: front-weighted (65%) + back (35%) → `overall_grade`
5. Extract defects, grade probability distribution
6. Handle image quality warnings (blurry, glare)

## System prompt — ключевые правила (anti-hallucination)

- **Only report VISIBLE defects** — никаких "microscopic flaws"
- **Creases cap grade at 6**
- **Clean cards = 9+**
- **Don't invent** if uncertain
- JSON-only response (no markdown)
- Front/back evaluated **separately** перед combining
- 60/40 weighting toward front

## Grade probabilities

Returns distribution: `{"1": 0, "2": 0, ..., "8.5": 0.6, "9": 0.25, "10": 0}` — для confidence visualization в UI.

## Dependencies

- `google.genai` — `Client`, `types` (Part, GenerateContentConfig)
- `json`, `re` — response parsing
- `dataclasses`

## Известные edge cases

- Holographic cards: surface может выглядеть scratched, Gemini может зафейлить — guidance в promt
- Sleeve обрезает edges → grade лучше с extracted/warped image (perspective corrected)

## Связанные

- API: [[../endpoints/gemini-grade]]
- Identification: [[gemini_identify]]
- Grading MOC: [[../../02-grading/_MOC]]
- 4 pillars: [[../../02-grading/pillars-overview]]
- Roadmap (OpenCV layer): [[../../02-grading/defect-detection/architecture]]
