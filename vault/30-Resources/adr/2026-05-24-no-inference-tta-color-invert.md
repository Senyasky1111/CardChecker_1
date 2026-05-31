---
type: adr
status: accepted
date: 2026-05-24
supersedes:
superseded-by:
area: [ml, grading]
tags: [adr, inference, augmentation, tta, sfx]
---

# Drop inference-time color-invert TTA from v3 plan

## Context

The v3.1 plan included Section M:
- **Training**: color-invert augmentation p=0.3 (model learns invert-invariance)
- **Inference**: 2-pass TTA on (MAIN, invert(MAIN)) when SFX missing → average confidences (~×2 latency, expected +1-3% mAP)

Stakeholder asked to clarify what "negative" means in our pipeline. Side-by-side comparison ([store_listing/v3_sample/diag_main_vs_sfx_vs_invert.jpg](../../../store_listing/v3_sample/diag_main_vs_sfx_vs_invert.jpg)) made it clear:

- **SFX** (TAG raking light photo) reveals **physical 3D relief** of the card surface — actual scratches/dents/wear show up as shadow contrast. This is what TAG calls "stereo" view.
- **Color invert** (255 − pixel) is just a digital colour complement of MAIN — adds no new physical information about surface defects.

These are not equivalent. Pretending color-invert substitutes for SFX at inference was a category error in the v3.1 plan.

## Decision

**Keep**: color-invert as TRAINING augmentation (p=0.3) — model becomes robust to colour distribution shifts (holo-glare false positives, foreign-language card prints with different ink saturation).

**Drop**: color-invert as INFERENCE TTA — does not provide the missing physical signal SFX would, so the ×2 latency cost (~600 ms → ~1.2 s) is not justified by the marginal expected gain (≤1% mAP on hard cases, mostly noise).

## Rationale

1. **Color invert ≠ relief**: SFX shadows encode 3D depth via raking-light physics. Color invert is a pointwise involution `f(x) = 255 − x` — zero new spatial / geometric information. Published TTA gains in 2024-2026 detection benchmarks (Ultralytics, TTA-OOD lit.) come from **spatial transforms (multi-scale, hflip)**, not pointwise colour ops applied on top of a model already trained with colour augmentation.
2. **Latency budget tight**: Hetzner GEX44 budget is ~500 ms p50 for full pipeline. Doubling Model A inference would push p95 past 2 s SLA.
3. **Cheaper alternatives waiting**: a generative-SFX-from-MAIN auxiliary (queued for v1.5; see "When to revisit" below) attacks the right gap.
4. **Sanity-check via Round-4 validation**: independent agent confirmed the decision is technically sound and identified the substitution as a category error (color-invert and SFX are not in the same hypothesis class).

## Training-aug retention — why p=0.3 invert is safe

Generic colour jitter is known to harm fine-grained colour features (Planckian Jitter 2022). We keep invert specifically because it **preserves edge magnitude** `|∇I|` — defects appear by gradient discontinuity, not by absolute hue. Invert flips polarity but not the magnitude of edges, so the model still sees defect signatures. Hue jitter would not have this property.

## Alternatives considered

- **Keep both**. Reject: latency cost not earned.
- **Drop both** (no color invert at all). Reject: training aug is genuinely useful for holo robustness, costs nothing, edge magnitude preserved.
- **hflip TTA at inference**. Reject for Pokemon cards — they have asymmetric text (HP, attack costs); flipping would break OCR-conditioned features. But a free option for non-card domains.
- **Multi-scale TTA** (the actual published TTA winner, +1-2% mAP). Hold — costs ×2-3 latency on detection transformers. Will A/B-test in v1.5 if we have latency headroom.
- **Sobel/gradient pseudo-SFX baseline**. Cheap (~1 day ablation): compute Sobel magnitude as a 7th input channel and check if it captures any SFX-like surface relief signal. Worth running BEFORE committing GPU budget to generative SFX in v1.5.
- **Inference TTA with CLAHE / gamma**. Hold — same category as multi-scale, evaluate in v1.5.

## Consequences

### Positive
- Inference latency stays in budget on Hetzner GEX44 / Modal serverless.
- v3 plan stops conflating SFX with digital tricks — terminology cleaner.
- Saved engineering time not implementing 2-pass forward pipeline.

### Negative
- ~1 % mAP not gained on MAIN-only inference. Acknowledged, deferred to v1.5 photometric track.
- If photometric prediction proves too hard in v1.5, we may revisit inference TTA — but only with a non-trivial operator, not naive color invert.

## When to revisit

### v1.5 generative-SFX-from-MAIN experiment (NOT classical photometric stereo)

Earlier draft of this ADR mentioned "single-image photometric estimation". Independent review flagged this as unrealistic — classical photometric stereo (IGA-PSN, MPS-Net) requires ≥3 lights and assumes Lambertian surfaces, while cards have heavy specular + holo highlights. Realistic v1.5 approach is **generative relighting**:

- **GenLit** (SIGGRAPH Asia 2025) — single-image relighting via diffusion priors
- **SVBRDF-with-highlights diffusion** (2025) — recovers spatially-varying reflectance from a single phone photo

Output is a qualitative SFX-like map (not metric depth), used as a 7th input channel to Model A. Good enough as auxiliary signal, not as ground truth.

Pre-experiment 1-day ablation: **Sobel-magnitude as 7th channel** — if model gains nothing from a classical edge map, generative SFX probably won't help either. Run this before spending GPU budget.

### Measured ablation needed

Earlier draft cited "~1% mAP" gain for invert TTA without evidence. Before re-opening this ADR, run measured ablation:
- 100 random TAG-holdout cards with SFX zeroed
- Compare: MAIN-only baseline vs MAIN + invert TTA vs MAIN + Sobel-channel vs MAIN + generative-SFX
- Decision rule: re-enable any TTA only if it gains >1.5% mAP and adds <300ms latency

## Related

- [[../../_context-packs/v3-defect-detection-plan]] — main plan (Section M will be updated to reflect this ADR)
- [[../../20-Areas/09-ml-research/_MOC]]
- [[../../log#2026-05-24]]
