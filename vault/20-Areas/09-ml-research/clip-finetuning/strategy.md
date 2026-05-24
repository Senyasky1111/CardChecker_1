---
type: note
status: experimental
area: [ml, recognition]
tags: [clip, finetuning, embeddings]
created: 2026-05-23
updated: 2026-05-23
---

# CLIP Fine-tuning Strategy

> Fine-tune CLIP ViT-L/14 vision encoder, чтобы embeddings были более robust к user photo distribution.

## Зачем fine-tune

Pretrained CLIP отлично generic, но:
- **Domain shift**: trained на web images, не на card scans
- **Pose sensitivity**: same card photographed at different angles → significantly different embedding
- **Lighting / glare**: holo cards особенно teach pretrained CLIP что glare = different identity

Even with [[../../30-Resources/adr/2026-05-23-clip-fallback-uses-warped-image|warping pre-processing]] остаются residual differences между warped user photo и studio scan.

## Approach

Contrastive fine-tuning на **synthetic positive pairs**:
- Anchor: clean studio scan (canonical, warped)
- Positive: same card processed через realistic augmentation pipeline (glare overlay, sleeve, brightness jitter, slight perspective leftovers)
- Implicit negatives: in-batch other cards

**Frozen text encoder** — мы не используем text branch CLIP, нет смысла его трогать.

## Training script

`scripts/finetune_clip.py` (~225 строк):
- Loads OpenCLIP `ViT-L/14`
- Freezes everything except vision encoder
- AdamW, low lr (~1e-6 для backbone, 1e-4 для head)
- Contrastive loss с temperature 0.07
- Eval: retrieval@1 на holdout set реальных user photos

## Pairs generation

См. [[pairs-generation]]. `scripts/generate_training_pairs.py` создаёт synthetic positive pairs.

## Status (2026-05-23)

**Experimental** — не deployed в проде. Embedding index в проде использует pretrained CLIP (см. [[../embedding-index/build-process]]).

Перед deployment нужно:
- [ ] Benchmark retrieval accuracy fine-tuned vs pretrained на ≥500 labelled user photo / card pairs
- [ ] Verify нет catastrophic forgetting на out-of-domain queries
- [ ] Rebuild embedding index с fine-tuned encoder
- [ ] A/B test в `/identify-v2` fallback path

См. [[../experiments-log]] для current state.

## When this might happen

После того как:
- Соберём достаточно labelled real-world pairs (eBay photos + ground truth identity)
- Production OCR-первый path стабильный enough что мы окей с потенциальным regression в CLIP fallback во время tuning

## Related

- [[pairs-generation]]
- [[../embedding-index/build-process]]
- [[../../06-api/modules/recognizer]]
- [[../../30-Resources/adr/2026-05-23-clip-fallback-uses-warped-image]]
