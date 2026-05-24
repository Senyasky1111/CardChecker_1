---
type: note
status: stable
area: [ml, detection, data]
tags: [yolo, dataset, synthetic]
created: 2026-05-23
updated: 2026-05-23
---

# YOLO Card Detection — Synthetic Dataset

> Synthetic composite dataset для training YOLO-pose card detector.

## Зачем synthetic

Real-world labelled card photos с corner annotations — expensive to collect at scale. Studio scans есть в massive количестве (50K+ from TCGdex + CardMarket image scrapes), но они изначально clean — нет угла, нет фона.

Synthetic compositing закрывает gap: берём clean card, размещаем на random background с realistic transforms.

## Pipeline

`scripts/generate_yolo_dataset.py` (~545 строк):

1. **Sample card image** из `data/cards/<lang>/<set>/<card>.jpg`
2. **Sample background** — procedural (gradients, noise) + real photo backgrounds
3. **Random transform**:
   - Perspective skew (±30°)
   - Rotation (±15°)
   - Scale (40-90% of frame)
   - Brightness / contrast jitter
   - Optional glare overlay
   - Optional sleeve overlay (semi-transparent)
4. **Composite** карта on background с alpha blend
5. **Compute keypoints** — projected corners after transform
6. **Output**:
   - `images/train|val/*.jpg`
   - `labels/train|val/*.txt` (YOLO-pose format: `class cx cy w h k1x k1y v1 k2x k2y v2 ...`)
   - `data.yaml` config

## Format

YOLO-pose label per image:
```
0 0.512 0.487 0.642 0.815  0.21 0.18 2  0.83 0.16 2  0.81 0.79 2  0.20 0.81 2
```
- `0` = card class
- `cx cy w h` = bbox normalized
- 4 keypoints: `kx ky visibility` (visibility always 2 since corners сами по себе видимы post-warp)

## Size

- Train: ~10K composites
- Val: ~1K composites
- Total disk: ~5 GB
- Generation time: ~30 min на M-class CPU

## Augmentation philosophy

Цель: train model to be robust where real user photos vary, **not** где они никогда не варьируются. Поэтому:
- ✅ Perspective, scale, lighting, partial occlusion
- ❌ Vertical flip (cards have orientation)
- ❌ Heavy color shift (would hurt set/rarity disambiguation — although not used by detector itself)

## When to regenerate

- Меняем canonical resolution
- Добавляем new edge cases (видим в production: pattern X не detected → add similar synthetic samples)
- Меняем backbone (some models prefer different aug)

## Related

- [[training]]
- [[../../05-data-pipelines/_MOC]]
- Backgrounds source: scraped eBay user photos через `scripts/scrape_ebay_photos.py`
