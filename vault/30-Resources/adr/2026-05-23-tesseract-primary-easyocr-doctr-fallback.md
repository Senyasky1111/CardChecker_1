---
type: adr
status: accepted
date: 2026-05-23
supersedes:
superseded-by:
area: [recognition, ocr]
tags: [adr, ocr, tesseract, easyocr, doctr]
---

# Tesseract primary OCR, EasyOCR + doctr as alternates

## Context

Для `/identify-v2` pipeline нужно извлекать с карты:
- Номер карты (e.g. "150/165") — bottom-left/right
- Название карты — top, varies by set
- Set symbol/code — bottom

Карты в **3 языках**: EN (Latin), JP (Kanji+Kana), TW (Traditional Chinese).
Constraints: backend CPU-only, single uvicorn worker, latency budget <100ms total для `/identify-v2`.

## Decision

**Tesseract** как primary OCR для всех языков.
**EasyOCR** как fallback когда Tesseract confidence низкий или текст не парсится.
**doctr** для специальных кейсов JP/TW где Tesseract систематически ошибается (текущее использование narrow).

Все три обёрнуты в `src/ocr.py` через единый interface.

## Alternatives considered

- **EasyOCR only** — отлично работает out-of-box, JP/TW handling лучше чем Tesseract. **Reject as primary**: 5-10× медленнее на CPU, требует PyTorch в проде.
- **PaddleOCR** — топ accuracy особенно для CJK. **Reject**: тяжёлый install, китайский ecosystem, GPU-oriented.
- **Vision API (Google/Azure)** — accurate, но **reject**: external dependency, cost per image, latency, privacy (user card photos).
- **doctr only** — modern, transformer-based, good multi-lingual. **Reject as primary**: heavier than Tesseract, не дозрел для production reliability на нашем CPU.
- **Gemini Vision** — используется отдельно для `/gemini/identify` fallback, но не для primary OCR — слишком дорого/медленно.

## Consequences

### Positive

- **Fast**: Tesseract обычно <30ms на одно поле card
- **CPU-only**: zero GPU dependency на сервере
- **Mature**: Tesseract — battle-tested, broad language support через trained data
- **Tiered fallback** — escalation цена платится только когда нужно
- **doctr** как escape hatch для JP/TW edge cases

### Negative / risks

- **Tesseract на JP/TW** уступает специализированным моделям → fallback chain срабатывает чаще для не-EN карт
- **Tuning complexity**: пороги уверенности для escalation между engines требуют maintenance
- **Three engines** = три места где может сломаться dependency / version

## Implementation

- `src/ocr.py` — единый OCR interface, hides engine selection
- `src/doctr_detector.py` — doctr-specific wrapper
- Tesseract data: `tessdata/` (gitignored)
- Used by: `src/card_matcher.py` (через ocr.py), `/detect-number` endpoint

## When to revisit

- Если accuracy на JP/TW becomes blocker (см. [[../../10-Projects/2026-Q2-jp-tw-ocr-accuracy]])
- Если на сервере появится GPU → можно EasyOCR/PaddleOCR primary
- Если doctr дозреет → может вытеснить Tesseract как primary

## Related

- [[../../20-Areas/06-api/modules/ocr]]
- [[../../20-Areas/06-api/modules/doctr_detector]]
- [[../../10-Projects/2026-Q2-jp-tw-ocr-accuracy]]
