---
type: adr
status: accepted
date: 2026-03-21
supersedes:
superseded-by:
area: [grading, ml]
tags: [adr, gemini, grading, llm]
---

# Use Gemini Vision for grading (initially), not custom-trained model

## Context

Grading требует:
- Оценку состояния по 4 столпам (centering, corners, edges, surface)
- PSA-style шкалу 1-10
- Detection of defects (whitening, scratches, dings)
- Front + back support
- Готовое решение **сейчас**, не через 6 месяцев

Альтернативы:
- Custom-trained CNN на TAG data (план есть, см. [[../../20-Areas/02-grading/defect-detection/architecture]])
- Gemini Vision 2.5 Flash с structured prompt
- OpenAI GPT-4V с prompts

## Decision

**Gemini 2.5 Flash** через `google.genai` SDK с подробным system prompt (70+ строк калибровочных правил, anti-hallucination rules).

**Custom model = roadmap**, не блокер для launch.

## Alternatives considered

- **Custom CNN** на TAG data
  - **Pro**: точнее, дешевле per-grade на масштабе, no API dependency
  - **Reject (для now)**: 3-6 месяцев работы (data labeling, training, calibration). Нужен product сейчас.
- **GPT-4V**
  - **Pro**: возможно качественнее для edge cases
  - **Reject**: дороже, slower, hard to enforce structured JSON output
- **No grading at all (defer feature)**
  - **Reject**: grading = ключевой differentiator от collector apps без AI

## Consequences

### Positive

- **Shipped в weeks**, не months
- **Quality acceptable** — Gemini handles 80%+ cards correctly при правильном промпте
- **Iterate fast** на prompt — не нужен retrain
- **Multi-lang support** out of box (Gemini понимает JP/TW текст на картах для context)
- **Defect descriptions** (DINGS-style) включены в response — UI может показать

### Negative / risks

- **API cost** ~$0.01-0.02 per grade — критично если scale to millions
- **Latency 2-5s** — пользователь ждёт, plus rate limits
- **API dependency** — если Gemini down, grading недоступен
- **Calibration drift** — Google может update model и наш promt перестанет work
- **No control over edge cases** — black box

### Mitigation

- **Anti-hallucination rules** в prompt (creases cap at 6, clean cards 9+, only VISIBLE defects)
- **OpenCV pre-layer** план — image quality gate отсекает плохие фото до Gemini ([[../../20-Areas/02-grading/defect-detection/architecture]])
- **Custom model train track** идёт параллельно — будет ready через ~6 месяцев

## Implementation

- `src/gemini_grade.py` — 458 lines
- API endpoint: [[../../20-Areas/06-api/endpoints/gemini-grade]]
- Used by: mobile (`gradingApi.ts`), webapp (`ConditionCheck.jsx`)
- Cost monitoring: пока не реализован, надо добавить

## When to revisit / migrate

Migrate to custom CNN когда:
- Cost становится > $1000/mo
- Latency budget ниже 1s required
- Custom model training достигает >85% accuracy vs TAG ground truth
- Gemini meaningfully degrades quality (unlikely)

См. [[../../20-Areas/02-grading/defect-detection/architecture]] для plan migration.

## Related

- Architecture: [[../../20-Areas/02-grading/defect-detection/architecture]]
- API: [[../../20-Areas/06-api/endpoints/gemini-grade]]
- Module: [[../../20-Areas/06-api/modules/gemini_grade]]
- ML roadmap: [[../../20-Areas/09-ml-research/defect-yolo/strategy]]
- Project: [[../../10-Projects/2026-Q2-opencv-defects]]
