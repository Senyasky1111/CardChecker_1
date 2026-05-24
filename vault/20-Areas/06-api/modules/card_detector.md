---
type: module
status: active
source: src/card_detector.py
lines: 646
related: [[yolo_card_detector]], [[doctr_detector]], [[../endpoints/detect-card]]
area: [backend, detection]
tags: [module, detection, opencv]
created: 2026-05-21
updated: 2026-05-21
---

# card_detector.py

> **TL;DR**: OpenCV-based card boundary detection + perspective correction в 600×825. Fallback backend если YOLO/DocTR недоступны.

## Public surface

- `DetectionResult` (dataclass) — `corners` (4×2), `confidence`, `method`, `card_found`, `warped`
- `CardDetector` — OpenCV fallback class with `detect(image) → DetectionResult`
- Module-level utils:
  - `get_detector(backend)` — factory: `"auto"`, `"yolo"`, `"opencv"`, `"doctr"`
  - `order_corners()`, `warp_card()`, `visualize_detection()`
  - `check_passthrough()` — определяет уже-кропнутую карту

## Internal flow

1. **`check_passthrough()`** — если aspect ratio ±5% от card ratio + width 350-900px → пропустить детекцию, просто resize
2. **Contour detection**:
   - Multi-edge maps: adaptive Canny + Otsu + CLAHE
   - Find largest 4-point contour
   - Score by aspect ratio, area, convexity, angles
3. **Hough fallback**:
   - Group lines by angle (horizontal/vertical)
   - Pick edge pairs → 4 intersections
4. **Fallback**: assume entire image is card
5. **Perspective warp** to 600×825

## Method values

- `contour` — OpenCV contour detection
- `hough` — Hough line detection
- `fallback` — couldn't find, treat whole image as card

## Dependencies

- `cv2` (OpenCV)
- `PIL.Image`
- `numpy`

## Notable patterns

- **Multi-strategy edge detection** (3 blur sizes + Otsu + CLAHE) — robust к glare, shadows
- **Corner subpixel refinement** (`cv2.cornerSubPix`)
- Aspect ratio tiebreaker: rejects detections >92% или <2% от image
- **Lazy YOLO/DocTR loading** — только если backend requested

## Производительность

- ~100-200ms per image (CPU only)
- Hough fallback: ~200-300ms

## Связанные

- YOLO version: [[yolo_card_detector]] (preferred, ~50-100ms)
- DocTR version: [[doctr_detector]] (text-region based)
- API: [[../endpoints/detect-card]]
- Comparison: [[../../01-recognition/detection/benchmark-comparison]]
