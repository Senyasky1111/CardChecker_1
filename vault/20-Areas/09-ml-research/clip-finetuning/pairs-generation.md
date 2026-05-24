---
type: note
status: stable
area: [ml, recognition, data]
tags: [clip, dataset, synthetic-pairs]
created: 2026-05-23
updated: 2026-05-23
---

# CLIP — Pairs Generation

> Synthetic positive pairs для contrastive fine-tuning CLIP.

## Script

`scripts/generate_training_pairs.py` (~298 строк).

## What it does

Берёт clean card scan и генерирует **realistic-looking degraded version**. Pair = (clean, degraded), label = "same card".

## Augmentations applied (random combos)

- **Glare overlay** — semi-transparent white blob на random location (mimics holo glare)
- **Sleeve overlay** — slight translucent sheen + minor distortion (mimics card в protective sleeve)
- **Lighting jitter** — brightness ±0.3, contrast ±0.2, gamma 0.8–1.2
- **Color cast** — random hue shift ±10° (mimics ambient lighting color)
- **Perspective remnant** — small residual skew post-warp (since real warp not perfect)
- **Noise** — Gaussian + JPEG re-compression
- **Crop jitter** — ±5% margin variation (warp output не pixel-perfect)
- **Defocus** — small Gaussian blur

Никогда не применяется:
- Rotation > 180° (changes identity for cards с asymmetric orientation)
- Vertical flip
- Heavy color shift (would change perceived rarity/foiling)

## Output

- `data/clip_pairs/anchor/*.jpg` — clean canonical scans
- `data/clip_pairs/positive/*.jpg` — corresponding degraded versions
- `data/clip_pairs/pairs.csv` — anchor_path,positive_path,card_id

## Volume

~50K pairs (one per card в catalog), regenerated periodically с different random seeds для diversity.

## Quality control

Spot-check sample: degraded version recognisable to human as same card? Some augmentations (heavy glare + heavy blur) may produce overly hard positives. Tune intensity if fine-tune loss not decreasing.

## Related

- [[strategy]]
- [[../yolo-card-detection/dataset]] — похожий подход для detection
