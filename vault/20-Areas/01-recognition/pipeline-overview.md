---
type: module
status: active
created: 2026-05-21
updated: 2026-05-21
area: [recognition, backend]
tags: [pipeline, recognition, end-to-end]
related: [[_MOC]], [[../06-api/endpoints/identify-v2]], [[../06-api/modules/card_matcher]]
---

# Recognition Pipeline — End-to-End

> **TL;DR**: От raw photo до identified card. **OCR-first** подход — CLIP только как fallback/rerank. ~100ms на хорошем фото.

## Полный pipeline

```
┌────────────┐
│ Raw photo  │  e.g. iPhone shot, может быть angled, в sleeve
└─────┬──────┘
      ↓
┌─────────────────────────────────────────────────┐
│ STEP 1: Card Boundary Detection                 │
│ • YOLO-pose (preferred, ~50-100ms)              │
│ • OpenCV contour/Hough (fallback)               │
│ • DocTR text-based (для sleeves)                │
│ Output: 4 corners                                │
└─────┬───────────────────────────────────────────┘
      ↓
┌─────────────────────────────────────────────────┐
│ STEP 2: Perspective Correction                  │
│ • Warp в каноничный 600×825                     │
│ • Expand corners 2% (collector number strip)    │
└─────┬───────────────────────────────────────────┘
      ↓
┌─────────────────────────────────────────────────┐
│ STEP 3: OCR Extraction                          │
│ • Name extraction (top banner, 2-pass)          │
│   - Tesseract PSM 7 → PSM 6                     │
│   - EasyOCR fallback                            │
│ • Collector number (bottom strip, 3 strategies) │
│   - 3 preprocessing variants                    │
│ • Language detection (JP/TW/EN)                 │
└─────┬───────────────────────────────────────────┘
      ↓
┌─────────────────────────────────────────────────┐
│ STEP 4: 5-Level SQL Lookup                      │
│ Strategy ladder (most specific → most general): │
│   L1: number + set_code (exact match)           │
│   L2: number + total + language                 │
│   L3: number + name fuzzy                       │
│   L4: name only (fuzzy)                         │
│   L5: empty → CLIP fallback                     │
└─────┬───────────────────────────────────────────┘
      ↓ (if SQL miss or low confidence)
┌─────────────────────────────────────────────────┐
│ STEP 5: CLIP/FAISS Fallback (optional)          │
│ • Generate embedding                            │
│ • FAISS L2 search top-K                         │
│ • Rerank when multiple candidates same name     │
└─────┬───────────────────────────────────────────┘
      ↓
┌─────────────────────────────────────────────────┐
│ STEP 6: Enrichment                              │
│ • CardMarket URL (locale-aware)                 │
│ • TCGPlayer URL                                 │
│ • PriceCharting URL                             │
│ • eBay sold URL                                 │
│ • Multi-source prices (prices_external table)   │
└─────┬───────────────────────────────────────────┘
      ↓
┌────────────┐
│ Card +     │ {tcgdex_id, name, prices, URLs, ...}
│ confidence │
└────────────┘
```

## Latency budget

| Step | Typical | Bottleneck |
|------|---------|------------|
| 1. Detection | 50-100ms | YOLO ONNX inference |
| 2. Warp | <5ms | OpenCV warpPerspective |
| 3. OCR | 30-150ms | Tesseract (или EasyOCR fallback) |
| 4. SQL lookup | <5ms | SQLite, indexed |
| 5. CLIP fallback | 500-1000ms | **Only on miss** — rare path |
| 6. Enrichment | <5ms | SQL |
| **Total (happy path)** | **~100ms** | OCR dominates |
| **Total (CLIP fallback)** | ~1-2s | CLIP inference |

## Confidence values

См. [[../06-api/modules/card_matcher]] — confidence varies by method:
- OCR exact (number + name match) → 0.95
- OCR name only → 0.7-0.99 (fuzzy score based)
- CLIP fallback → 0.75
- Number only (no name) → 0.35-0.7 (forces Gemini fallback в client)

## Multi-language handling

- **Language detection** в OCR: Hiragana/Katakana → JP, CJK-only → TW, else EN
- **SQL lookup** language-aware (filter at query time)
- **Tiebreaker** для name fuzzy: JP > EN > TW (так как JP оригиналы)
- **Fallback к eng_name** для JP/TW при CardMarket URL generation

## Failure modes

| Scenario | Behavior |
|----------|----------|
| Не нашли card boundary | Whole image as card (fallback method) |
| OCR не извлёк ни name ни number | CLIP fallback, низкая confidence |
| SQL не нашёл match | CLIP fallback, return top similar visual matches |
| Всё провалилось | `success: false`, пустые candidates |

## Используется в

- `/identify-v2` endpoint (preferred) — этот pipeline целиком
- `/identify` endpoint (legacy) — больше weight на CLIP
- `/gemini/identify` — bypass всего pipeline, делегирует Gemini

## Связанные

- Main module: [[../06-api/modules/card_matcher]]
- API: [[../06-api/endpoints/identify-v2]]
- Detection variants: [[detection/yolo-pose]], [[detection/opencv-contours]]
- OCR variants: [[ocr/tesseract]], [[ocr/easyocr]], [[ocr/doctr]]
- Matching strategies: [[matching/5-level-sql-lookup]], [[matching/clip-faiss-fallback]]
