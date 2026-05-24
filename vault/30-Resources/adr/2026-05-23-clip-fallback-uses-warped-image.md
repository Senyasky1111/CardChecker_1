---
type: adr
status: accepted
date: 2026-05-23
supersedes:
superseded-by:
area: [recognition, matching]
tags: [adr, clip, warping, matching]
---

# CLIP fallback uses warped card image, not raw photo

## Context

`/identify-v2` pipeline: detection → OCR → 5-level SQL lookup. Когда SQL match fails (OCR text не cleanly соответствует ни одной карте), falls back to **CLIP visual matching** against pre-computed embedding index 50K+ карт.

Изначально CLIP fallback использовал **raw user photo** (после detect → crop, но без perspective warp). Embedding index был построен на reference **studio-quality scans** (центрированных, прямых, чистый фон).

Domain gap → плохой match accuracy на криво сфотографированных user photos.

## Decision

**CLIP embeddings вычисляются на warped image** — после `cv2.getPerspectiveTransform()` корректирует карту в canonical orientation (632×880 portrait или landscape).

Embedding index перестроен с тем же warped pre-processing на reference scans (через `scripts/build_embedding_index.py`).

## Alternatives considered

- **Raw photo + larger embedding index** — увеличить index чтобы включить аугментированные (rotated/perspective-distorted) reference копии. **Reject**: 5-10× больше embeddings, дороже к compute и storage, всё равно не covers все возможные углы.
- **Fine-tune CLIP** на распарсенных user photos (paired training: photo ↔ canonical scan). **Hold for now** — см. `scripts/finetune_clip.py`, experiment running. Но даже с finetune warp всё равно полезен.
- **Multiple embeddings per card** (front + back + rotated views) — **partial**: сейчас одна front canonical. Может расширим если надо.

## Consequences

### Positive

- **Closes domain gap** — user photo и reference оба warped to canonical → similar embedding space
- **Top-1 accuracy growth** with warped CLIP fallback (estimated from internal testing, не зафиксировано в metrics ноуте)
- **Reuses existing detection pipeline** — warping и так делается для OCR, нет extra compute
- **Embedding index stays small** (50K embeddings, ~150 MB)

### Negative / risks

- **Detection quality bottleneck** — плохой warp → плохой embedding. YOLO-pose accuracy критичен (см. [[2026-05-23-yolo-pose-not-opencv-detection]])
- **Edge cases**: карта почти не видна / partial occlusion → warp = garbage → CLIP даёт wrong-but-confident match. Confidence threshold на CLIP output должен это catch'ить.
- **Re-index cost** — если меняем canonical resolution или CLIP backbone, нужно пересчитать все 50K embeddings (~30min на CPU)

## Implementation

- Warping logic: `src/card_detector.py` + `src/yolo_card_detector.py` (oба вызывают `getPerspectiveTransform`)
- CLIP embedding: `src/recognizer.py`
- Index build: `scripts/build_embedding_index.py`
- Integration: `src/card_matcher.py` (level 5 fallback после 4 SQL levels)

## Related

- [[../../20-Areas/01-recognition/matching/5-level-sql-lookup]]
- [[../../20-Areas/06-api/modules/recognizer]]
- [[../../20-Areas/06-api/modules/card_matcher]]
- [[2026-05-23-yolo-pose-not-opencv-detection]]
