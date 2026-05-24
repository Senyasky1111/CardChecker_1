---
type: api-endpoint
method: POST
path: /gemini/grade
status: active
latency-p95: ~3-5s
source: src/api.py:1193-1253
related: [[../modules/gemini_grade]], [[../../02-grading/_MOC]]
area: [backend, api, grading]
tags: [api, grading, gemini, llm, psa]
created: 2026-05-21
updated: 2026-05-21
---

# POST /gemini/grade

> **TL;DR**: AI grading через Gemini 2.5 Flash. PSA-style 1-10 шкала, 4 столпа (centering/corners/edges/surface), front 65% + back 35%.
> Главный grading endpoint — используется mobile + webapp.

## Request

| Param | In | Type | Required | Description |
|-------|-----|------|----------|-------------|
| `file` | body | UploadFile | ✅ | Front image |
| `back_file` | body | UploadFile | ❌ | Back image (optional but recommended) |

## Response (`GeminiGradeResponse`)

```json
{
  "success": true,
  "processing_time_ms": 3850,
  "model_used": "gemini-2.5-flash",

  "overall_grade": 8.5,
  "grade_label": "PSA 8.5 / NM-MT+",
  "front_grade": 9.0,
  "back_grade": 7.5,

  "front": {
    "grade": 9.0,
    "centering": { "score": 9.0, "notes": "Slight L bias", "lr": "53/47", "tb": "50/50" },
    "corners": { "score": 9.5, "notes": "Sharp" },
    "edges": { "score": 9.0, "notes": "Minor whitening on right edge" },
    "surface": { "score": 9.0, "notes": "Clean, no scratches" }
  },
  "back": { ... same structure ... },

  // Legacy combined (for backward compat)
  "centering": { ... },
  "corners": { ... },
  "edges": { ... },
  "surface": { ... },

  "key_defects": [
    { "side": "back", "location": "top-right corner", "type": "whitening", "severity": "moderate", "visibility": "minor" }
  ],

  "explanation": "...",
  "grade_probabilities": { "1": 0, ..., "8": 0.25, "8.5": 0.60, "9": 0.15, "10": 0 },
  "image_quality_warning": null
}
```

## Pipeline

1. 503 if `_gemini_grader` is None (нет `GEMINI_API_KEY`)
2. Read front (required), validate MIME
3. Read back (optional)
4. `_gemini_grader.grade(front_bytes, back_bytes, mime_type)`:
   - System prompt с 70+ строками **anti-hallucination правил** (creases cap at 6, clean cards 9+)
   - Gemini evaluates **front and back separately** across 4 pillars
   - Returns per-side grades, overall, defect list, grade probabilities
5. `_side_to_response()` + `_pillar_to_response()` — конвертация dataclass → API response
6. Combine: front 65% + back 35% → overall

## Failure modes

- 503: `GEMINI_API_KEY` не задан
- 400: front не image MIME

## Anti-hallucination правила

System prompt в `gemini_grade.py:35-178` — ключевые:
- Only report VISIBLE defects (никаких "microscopic flaws")
- Creases cap grade at 6
- Clean cards = 9+
- Don't invent if uncertain

## Performance

- Typical: 2.5-5s
- p95: ~4s
- Stoимость: ~$0.01-0.02 per grade

## Image quality warning

Если фото blurry / glare → возвращается `image_quality_warning` с описанием. UI должен показать пользователю.

## Roadmap

См. [[../../02-grading/defect-detection/architecture]] — план добавить OpenCV pre-layer чтобы:
- Image quality gate отсекал плохие фото перед Gemini
- Centering считался deterministically (Sobel)
- Дешёвые карты получали OpenCV-only grade (skip Gemini)

## Связанные

- Module: [[../modules/gemini_grade]]
- Grading MOC: [[../../02-grading/_MOC]]
- Pillars: [[../../02-grading/pillars-overview]]
- Defect detection roadmap: [[../../02-grading/defect-detection/architecture]]
- Project: [[../../../10-Projects/2026-Q2-opencv-defects]]
- Webapp consumer: [[../../08-webapp/overview]]
