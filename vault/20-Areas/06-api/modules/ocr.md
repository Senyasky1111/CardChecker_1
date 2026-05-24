---
type: module
status: active
source: src/ocr.py
lines: 1119
related: [[card_matcher]], [[../endpoints/detect-number]]
area: [backend, recognition, ocr]
tags: [module, ocr, tesseract, easyocr]
created: 2026-05-21
updated: 2026-05-21
---

# ocr.py

> **TL;DR**: Самый большой модуль (1119 строк). Extract name + collector number из 600×825 card image. EN/JP/TW support. Primary: Tesseract (~30-80ms), fallback: EasyOCR.

## Public surface

- `CollectorNumber` (dataclass) — `number`, `total`, `set_code`, `raw_text`
- `CardOCRResult` (dataclass) — `name`, `collector_number`, `confidences`, `language`, `processing_time_ms`
- `CardOCR` — main OCR class:
  - `extract(image) → CardOCRResult`
- `detect_language(text) → 'ja' | 'zh-tw' | 'en'`

## Internal flow

### Name extraction (2-pass)

- **Standard crop** — top-banner
- **Extended crop** — for Trainer/Supporter (имя может быть ниже banner)
- Tesseract PSM 7 (single line) → PSM 6 (text block)
- EasyOCR fallback if Tesseract unavailable / low-confidence
- Clean artifacts: OCR noise, HP spillover, evolution text

### Collector number extraction (3-strategy)

1. **Strategy 1**: Tesseract на bottom 10% с 3 preprocessing methods (color upscale, sharpen, CLAHE)
2. **Strategy 2**: EasyOCR на full bottom strip
3. **Strategy 3**: Tighter right-bottom crop для old-era cards
- **Digit correction**: trim trailing/leading digits, substitute confusions (0↔8, 1↔7, i↔1)

### Language detection

- Hiragana/Katakana → JP
- CJK-only → TW
- else EN

## Dependencies

- `pytesseract` (Tesseract — auto-find в Windows registry paths)
- `easyocr.Reader`
- `cv2`, `PIL`, `numpy`
- `sqlite3` — load known set totals/codes для validation

## Notable patterns

- **Lazy EasyOCR readers**: separate `en_ja` vs `en_ch` (can't mix в одном reader)
- **Tesseract first** (fast), **EasyOCR fallback** (slow, multilingual)
- **Aggressive cleanup**: control chars, emoji, evolution text, HP bleed
- **Set code validation**: только known codes (через JSON), rarity markers filtered (AR, SAR, SR, etc.)
- **Hash-number fallback**: #NNN формат для old-era cards (Base, Neo, e-Card)

## Производительность

- Tesseract pass: ~30-80ms
- EasyOCR fallback pass: +100-200ms
- Card boundary detection (если делаем здесь, не передан): +50-100ms

## Известные проблемы

- **JP/TW accuracy** — слабое место, см. [[../../../10-Projects/2026-Q2-jp-tw-ocr-accuracy]]
- Holographic cards могут вызывать OCR artifacts (рассмотри [[doctr_detector]] как альтернативу)

## Связанные

- API: [[../endpoints/detect-number]], [[../endpoints/identify-v2]]
- Pipeline: [[card_matcher]]
- Alternative engines: [[../../01-recognition/ocr/ocr-engine-comparison]]
- Improvement project: [[../../../10-Projects/2026-Q2-jp-tw-ocr-accuracy]]
