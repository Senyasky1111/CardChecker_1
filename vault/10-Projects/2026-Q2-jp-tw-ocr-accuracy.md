---
type: project
status: planned
created: 2026-05-21
updated: 2026-05-21
priority: 3
target: 2026-Q2
area: [recognition, ml]
tags: [ocr, jp, tw, q2]
related: [[../20-Areas/01-recognition/languages/jp-recognition]], [[../20-Areas/01-recognition/languages/tw-recognition]]
---

# Project: Improve JP/TW OCR Accuracy

> **Priority #3**. Точность OCR на японских и тайваньских картах хуже чем на EN.

## Goal

Догнать EN-level точность распознавания для:
- JP карт (15K в DB)
- TW карт (12K в DB)

## Why

- EN OCR хорошо работает на Tesseract/EasyOCR
- JP/TW: иероглифика плохо распознаётся стандартными engine'ами
- Это **блокер для рынков** Japan и Taiwan
- TCGdex даёт нам metadata этих карт — мы их видим, но не распознаём

## Hypotheses (нужно проверить)

1. **doctr** ([[../20-Areas/01-recognition/ocr/doctr]]) лучше работает на JP/TW чем Tesseract?
2. Card-specific font fine-tuning OCR engine?
3. Использовать **только number** (цифры), и матчить только по нему + set?
4. CLIP fallback приоритетнее для JP/TW (т.к. OCR ненадёжен)?

## Phases

### Phase 1: Diagnostic
- [ ] Собрать 100 JP карт + 100 TW карт для бенчмарка
- [ ] Прогнать через текущий pipeline → ground truth → accuracy %
- [ ] Идентифицировать где именно теряем (OCR vs SQL match vs CLIP)

### Phase 2: OCR engine comparison
- [ ] Tesseract (текущий)
- [ ] EasyOCR (текущий)
- [ ] doctr (новый — [[../20-Areas/01-recognition/ocr/doctr]])
- [ ] Manga OCR (специально для JP)
- [ ] Возможно PaddleOCR (хорош на CJK)

### Phase 3: SQL match strategy
- [ ] Если OCR ненадёжен → больше веса на number + set?
- [ ] Можно ли матчить с пустым name?

### Phase 4: CLIP fallback tuning
- [ ] Понизить threshold для JP/TW?
- [ ] Specialized embedding index для JP/TW?

## Done means

- JP recognition accuracy ≥ 85% (с EN baseline ~95%)
- TW recognition accuracy ≥ 80%

## Связанные

- Recognition MOC: [[../20-Areas/01-recognition/_MOC]]
- OCR comparison: [[../20-Areas/01-recognition/ocr/ocr-engine-comparison]]
- Catalog: [[../20-Areas/04-catalog/tcgdex/jp-import]], [[../20-Areas/04-catalog/tcgdex/tw-import]]
