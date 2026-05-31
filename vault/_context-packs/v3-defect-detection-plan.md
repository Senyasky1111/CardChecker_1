---
type: context-pack
status: active
area: [ml, grading]
tags: [defect-detection, plan, v3]
created: 2026-05-24
updated: 2026-05-24
---

# CardChecker ML v3.2 — Final Plan (post-3-round-validation + stakeholder corrections)

> **Status**: canonical plan. Round 1 = 9 architecture amendments. Round 2 = 5 product amendments. Round 3 = 12 operational amendments incorporated (Tier-1). Tier-2 deferred to v1.1 sprint. Round 4 = pending (centering, augmentation, final-readiness validation). Stakeholder corrections layered on top (2026-05-24):
> - Defect classes stay at 7 (no split)
> - Quality gate = soft warning, NOT block
> - Output = grade + interval + full probability distribution over 19 buckets
> - Centering: validate against TAG's 96k L/R + T/B ratios (NOT untested CV)
> - Aggregator: fit on 1331 cards, **validate end-to-end on 41k cards** (NOT 100)
> - Color invert as training aug p=0.3 + inference TTA on MAIN-only
> - Recognition-first conditioning (use card DB when identified, aux head as fallback)
> - Targeted dozaliv: ~12 GB crop images for 1331 cards with per-zone scores

Read [[../log#2026-05-24]] for the decision trail.

## Mission (unchanged, fixed in memory)

Build a custom CV pipeline that, given phone photos of a Pokemon card, outputs:
1. **Visual defect heatmap** — bbox + class per visible defect
2. **Centering ratios** — L/R, T/B border ratios, deterministic
3. **PSA-style overall grade 1-10** + per-pillar sub-grades + `weakest_pillar` field

Compete with TAG / PSA AI / Ximilar on accuracy. Gemini Flash is interim baseline; this is the replacement.

## Architecture v3 — 4 models

### Model A — Defect Detector (revised, v3.1)

- **Architecture**: DEIMv2-S + DINOv3-ViT-L/16 (frozen + LoRA r=8 in last 4 blocks)
- **Bake-off**: RF-DETR-S (arXiv:2511.09554) vs DEIMv2 on 5k-card subset (~$15-20) BEFORE committing $60-90 to full train.
- **Bbox style**: class-conditional
  - **OBB** for `scratch`, `crease` (aspect-ratio > 3:1)
  - **AABB** for `corner_wear`, `edge_wear`, `surface_damage`, `dent`, `stain`
- **Input**: 1280px warp, 6-channel (MAIN-RGB + SFX-RGB)
  - **Modality dropout**: curriculum p=0.5→0.2, NEVER drop MAIN
  - **Modality-presence token**: learnable embed (MICCAI 2025, arXiv:2509.18284)
- **Output (primary)**: 7 defect classes
- **Output (auxiliary, NEW in v3.1)** — 3 multi-task classification heads sharing the backbone:
  - **`finish_head`** — 7 classes: `non_holo`, `reverse_holo`, `holo_classic`, `full_art`, `etched_textured`, `rainbow_gold`, `promo_special`
  - **`era_head`** — 5 classes: `Vintage` (1999-2003), `eCard/EX` (2003-2008), `DP-XY` (2008-2016), `SM-SwSh` (2016-2021), `SV+` (2022-)
  - **`language_head`** — 3 classes: `en`, `jp`, `tw`
- **Inference-time conditioning** (NEW):
  - Conditional NMS thresholds per finish (e.g. `holo_classic` → scratch threshold 0.65 vs 0.4 default)
  - Per-finish severity priors fed to Model B
  - Per-finish loss reweighting during training (holo cards: scratch loss × 0.7)
- **Training data**: 67 400 cards, SAM2-refined bboxes + Gemini-pseudo-labeled finish/era/language for 2 000 seed cards → bootstrapped via aux head to rest of corpus
- **Loss**: Varifocal + GIoU primary, CE for aux heads, Kendall-Gal uncertainty weighting across tasks
- **Compute**: H100 ~15h, **$60-90 (unchanged — aux heads share trunk)**

### Aux-head training data (NEW Section A7)

| Step | What | Cost | Time |
|---|---|---|---|
| A7a | Sample 2 000 random cards stratified by visual cluster (pHash buckets) | $0 | 30 min |
| A7b | Gemini Flash auto-label (finish, era, language) | ~$3-5 | 1 h |
| A7c | Hand-verify 200 random labels, fix systematic errors | $0 | 1 h mine |
| A7d | Train aux heads jointly with Model A in C2 | included | included |
| A7e | Pseudo-label all 65 400 remaining cards via trained aux heads | $0 | 30 min inference |

### Model B — Per-zone Severity Classifier (revised)

- **Architecture**: ConvNeXt-V2-Tiny + ORCU ordinal loss
- **Heads**: separate weights for corners and edges
- **Input**: 224×224 corner crop OR 480×96 edge strip from MAIN scan
- **Output**: 4-class ordinal severity using **TAG vocabulary**:
  - **clean** (TAG total ≥ 990)
  - **minor ding** (950-989)
  - **major ding** (800-949)
  - **disqualifying** (< 800)
  - Thresholds anchored to TAG-published Mint(950)/Pristine(990) floors, refined via percentile fitting on the 1 331-card strong-label set.
- **Training data**: 1 331 cards × 8 zones = ~10 000 strong labels
- **Multi-task aux**: 3-way A/B (no-aux / fixed-λ Poisson / uncertainty-weighted Poisson on 96k dings counters). Select by macro-F1 of `disqualifying` class on cert-prefix holdout, NOT by overall accuracy. Default OFF until measured benefit.
- **Compute**: A40 ~6h × 2 + extra A40 ~4h for A/B sweep = **$28-38**

### Model C — Centering Detector (algorithm + TAG-ground-truth validation)

- **Stage 1**: pure OpenCV (Sobel + bilateralFilter + Canny + Hough on margin band) on warped 600×825 card
- **Stage 2 fallback** (when Stage 1 confidence < 0.6): YOLOv8n-pose with 8 inner-frame keypoints, trained locally on RTX 4060 from ~500 hand-labeled cards
- **Borderless / full-art** (Stage 2 vis < 0.3): return `centering_subgrade = N/A`, weight aggregator over remaining pillars
- **Calibration**: piecewise step (55/45=10, 60/40=9, 65/35=8, 70/30=7, 80/20=6, 85/15=5)
- **GROUND-TRUTH VALIDATION (NEW in v3.2)**:
  - TAG provides `centering_front_lr` + `centering_front_tb` for **96 455 cards**
  - Parse TAG format carefully (some entries have cert-prefix concat artifact like `"0305656/47.74"`)
  - Validate algorithm output against TAG ratios → measure MAE in % ratio
  - **Fallback to learned regression model** (MobileNet → 4 numbers) if pure CV MAE > 3%
- **Compute**: $0 (CV) + 30 min local train

### Model D — Grade Aggregator (revised — CRITICAL)

> **Change from v2**: pure geomean was Ximilar's formula, not PSA's. PSA uses **weakest-link rule**. TAG explicitly compounds deductions on lower sub-grades.

- **Formula**: `overall = min(0.6·geomean(pillars) + 0.4·min(pillars), min(pillars) + 1.0)`
- **FIT**: blend weights (0.6 / 0.4) fit on **1 331 cards** with explicit pillar scores via constrained regression
- **VALIDATE END-TO-END (NEW v3.2)**: full pipeline (Model B predicts sub-grades, Model C measures centering, formula aggregates) compared vs TAG overall grade on **41 292 cards** with positive grade. Primary metric: Spearman ρ ≥ 0.85, MAE ≤ 0.5 grades.
- **Front/back combination**: `card_grade = 0.65·front + 0.35·back`
- **Corner sub-grade**: attention-pool over 4 corner severities, min-aware bias
- **Edge sub-grade**: mean-pool over 4 edge severities
- **Surface sub-grade**: regression head on full card → 0-100 → grade 1-10
- **Output contract** (refined v3.2 — full distribution per stakeholder):
  ```
  {
    overall_grade: 8.0,                    // mode of distribution, 1.0 - 10.0
    interval_95: [7.5, 8.5],               // 95% confidence interval
    distribution: {                         // softmax over 19 buckets (1.0, 1.5, ..., 10.0)
      "8.0": 0.80, "7.5": 0.10, "8.5": 0.06, "7.0": 0.03, ...
    },
    pillars: { centering: 78, corners: 65, edges: 92, surface: 85 }, // each 0-100
    weakest_pillar: "corners",
    confidence_tier: "high" | "medium" | "low",  // derived from distribution sharpness
    finish: ["holo_classic", "etched"],    // multi-label (sigmoid BCE)
    era: "SV+",                            // single-label (softmax)
    language: "en" | "jp" | "tw" | "other", // 4-class with abstain
    defect_heatmap: [{cls, bbox, conf, side}], // for UI overlay
    quality_flags: ["blurry"] | [],        // soft warnings, NEVER blocks
    conditioning_source: "recognition" | "aux_head"  // for telemetry
  }
  ```
- **Confidence formula** (NEW, was undefined in v3):
  ```
  c_A = mean(bbox_confidence) of bboxes whose class maps to weakest_pillar
  c_B = severity_softmax_margin at weakest_pillar's zone
  c_C = centering_stage_confidence (Stage 1 score or Stage 2 keypoint vis)
  disagreement_penalty = |implied_subgrade_from_A − subgrade_from_B| / 10.0
  confidence = min(c_A, c_B, c_C) * (1 − disagreement_penalty)
  ```
  Calibrated via Temperature Scaling on TAG-holdout. Output as 95% interval to UI: `grade 8.5 ± 0.7`.

## Section A — Data Foundation (revised)

| Step | What | Notes | Time | $ |
|---|---|---|---|---|
| A1 | Rebuild converter | corners[]/edges[] arrays + 5 692 negatives + class-typical bbox sizes (synthetic), then A4 refines | 3 h mine | 0 |
| A2 | Generate v3 detection dataset | 67 400 images, ~250k bbox labels | 1 h | 0 |
| A3 | Generate v3 severity dataset | 10k corner/edge crops × TAG strong labels | 30 min | 0 |
| A4 | **SAM2 with HITL gate** | zero-shot mask from (x,y), auto-reject by area/AR/border heuristic, hand-verify 300 random samples (~3h) | H100 4-6h + 3h mine | **$25-40** |
| A5 | **GroupKFold split** (cert-prefix + pHash≤6 cluster + grade-bucket) | NOT stratified by language/era (94% missing metadata). Hold out 1 cert-prefix group as generalization probe. | 30 min | 0 |
| A6 | Dataset doctor verify | ensure no cross-split cert leakage, balance grade-buckets | 10 min | 0 |
| A8 (NEW v3.2) | Targeted dozaliv: download corner/edge/surface crop URLs for 1 331 cards with per-zone scores | ~12 GB, 2 h | 0 |
| A9 (NEW v3.2) | Use 1 900 already-on-disk hi-res crops + 10 000 new dozaliv crops as bonus input for Model B | included in D1/D2 | 0 |

## Section B — Backbone SSL pretrain

| Step | What | Compute | $ |
|---|---|---|---|
| B1 | Continual DINOv3-ViT-L SSL on 67k unlabeled card scans | H100 16h | **$40-50** |
| B2 | Export adapted backbone | 5 min | 0 |

## Section C — Model A train (with bake-off)

| Step | What | Compute | $ |
|---|---|---|---|
| C0 | **RF-DETR vs DEIMv2 bake-off** on 5k subset, 30 epochs | A40 6h × 2 | **$15-20** |
| C1 | Local smoke test (500 imgs, 1 epoch) | RTX 4060 10 min | 0 |
| C2 | Full train winner | H100 15h | **$60-90** |
| C3 | `/review-run` post-mortem | 5 min | 0 |

## Section D — Model B train (parallel with C)

| Step | What | Compute | $ |
|---|---|---|---|
| D1 | Corners head + 3-way Poisson aux A/B | A40 6h + 4h sweep | **$15-20** |
| D2 | Edges head + 3-way Poisson aux A/B | A40 6h + 4h sweep | **$13-18** |
| D3 | `/review-run` post-mortem | 5 min | 0 |

## Section E — Centering (code only)

| Step | What | Compute |
|---|---|---|
| E1 | Implement `src/centering.py` Stage 1 (CV) | 1 day mine |
| E2 | Hand-label ~500 cards for keypoint train | 2 h mine |
| E3 | Train YOLOv8n-pose locally | RTX 4060 30 min |
| E4 | Calibration table constants | 30 min mine |

## Section F — Grade Aggregator (code only)

| Step | What | Compute |
|---|---|---|
| F1 | Fit blend weights via constrained regression on 1 331 cards | 1 h mine |
| F2 | Implement `src/grade_combiner.py` | 0.5 day mine |
| F3 | ADR documenting formula choice | 1 h mine |

## Section G — Integration & Eval

| Step | What | $ |
|---|---|---|
| G1 | New `/grade-v2` API endpoint | 1 day mine |
| G2 | Eval on 100 hand-labeled TAG holdout cards | 2 h |
| **G2.5 (NEW)** | **SFX-absent ablation eval** — re-run G2 with SFX channel zeroed + modality-token set to "absent". Reject plan if MAE delta > 0.3 grades. | 1 h |
| G3 | Compare vs Gemini Flash baseline (MAE, Spearman, per-pillar) — TAG-holdout only | 1 h |
| G4 | Write ADR + experiments-log + viz | 2 h |

**Note on real-world evaluation**: hand-photo benchmark explicitly skipped per stakeholder decision (2026-05-24). Assumption: users will take reasonably good photos (perpendicular angle, indoor lighting), and a future studio-rig accessory will further control conditions. v1 evaluation is ONLY on TAG-holdout — real-world accuracy will be measured post-launch via user telemetry + Gemini-as-judge sampling. This is a known limitation, accepted by stakeholder.

## Section H — Input Quality Gate (v3.2 — soft warnings, NOT blocker)

> **Changed in v3.2 per stakeholder**: gate does NOT block grading. Always grade, but **attach quality flags** so mobile UI can show warnings.

| Step | What | Compute |
|---|---|---|
| H1 | Train MobileNet-V3-Small binary heads (5 outputs): `is_card`, `in_sleeve`, `in_toploader`, `is_blurry`, `is_screen_photo` | RTX 4060 local, 30 min |
| H2 | Hand-label ~500 phone shots from mixed sources (own + Google image search) | 2 h mine |
| H3 | Wire into `/grade-v2` as pre-step — populate `quality_flags: [...]` in response, ALWAYS proceed to grading | 0.5 day mine |
| H4 | Tune thresholds on validation set to favour recall over precision | 30 min |

**API behaviour (v3.2)**: gate ALWAYS proceeds to grading. Response includes `quality_flags: ["blurry", "in_sleeve"]` (empty array if clean). Mobile decides what to show:
- empty flags → normal grade display
- non-empty → grade + soft warning banner "Photo quality may affect accuracy"

`card_in_sleeve` does NOT block — graded slabs are always sleeved.

## Section M — Color Invert Training Augmentation (v3.2, TTA dropped per ADR)

> **Revised 2026-05-24** per stakeholder clarification: SFX is physical raking-light photo with relief info, color-invert is just digital colour complement. These are NOT equivalent. Inference TTA dropped. See [[../30-Resources/adr/2026-05-24-no-inference-tta-color-invert]].

| Step | What | Compute |
|---|---|---|
| M1 | Training augmentation: color-invert each input image with p=0.3 (bboxes unchanged). Helps model learn robustness to colour distribution shifts (holo-glare, foreign-language ink). | $0, in C2 |
| ~~M2~~ | ~~Inference TTA~~ — **DROPPED**. Color invert does not substitute for SFX at inference (no new physical info). See ADR. | — |
| M3 | v1.5 future: train "predict SFX from MAIN" auxiliary, use predicted SFX as 2nd channel at inference. Single-image photometric estimation. | v1.5 |

## Section N — Recognition-First Conditioning (NEW v3.2)

> Strong insight from stakeholder: we already have a CLIP+OCR+SQL card-identification pipeline. When it succeeds, we know EXACTLY what card this is (set, year, finish, language) from the catalog. Use that instead of aux-head guesses.

| Step | What | Compute |
|---|---|---|
| N1 | If `recognize_card(photo)` succeeds with confidence > 0.85, fetch `(set_id, finish, era, language)` from card catalog. | $0 (already in pipeline) |
| N2 | Pass these as ground-truth conditioning to Models A & B (override aux-head predictions). | $0 |
| N3 | If recognition fails or confidence < 0.85, fall back to aux-head predictions. | already in plan |
| N4 | Telemetry: log `conditioning_source: "recognition" \| "aux_head"` for monitoring trust. | $0 |

**Why**: recognition is ~100% accurate on cataloged cards; aux head is ~85-95%. Free accuracy boost.

## Section I — Telemetry & Active-Learning Loop (NEW in v3.1)

> Without this, v1 quality is frozen forever. With this, every user interaction improves the model.

| Step | What | Compute |
|---|---|---|
| I1 | SQLite table `grade_events` with schema: `(photo_hash, request_ts, predictions_json, gate_flags, finish_predicted, user_feedback, gemini_judge_score, retrained_in_version)` | 1 h mine |
| I2 | Endpoint `POST /grade-feedback` for user to confirm/reject grade | 1 h mine |
| I3 | Weekly cron: sample 200 low-confidence + 200 model-vs-Gemini disagreements → label queue (Gemini-as-judge with `gemini-2.5-pro` for hard cases) | 30 min mine |
| I4 | Quarterly retrain on `TAG ∪ telemetry-labeled` | included in next cycle |

**Privacy**: photo hashes stored, NOT raw photos. Raw photos kept for 7 days then deleted unless user opts into "help improve the model".

## Budget (revised for v3.1)

| Phase | Cost | Time |
|---|---|---|
| Data prep + SAM2 HITL + SSL pretrain | $65-90 | 1-2 days |
| Aux-head label seed (Gemini for 2k cards) | $3-5 | 1 h |
| Detector bake-off + full train (includes 3 aux heads) | $75-110 | 1 day cloud |
| Severity heads + Poisson A/B | $28-38 | parallel with detector |
| Centering + aggregator + confidence calib + eval | $3 | 1 day mine |
| Input quality gate (local train) | $0 | 0.5 day mine |
| Telemetry schema + endpoint | $0 | 0.5 day mine |
| **TOTAL first iteration** | **$174-246** | **~4.5 working days** |

Still tight against $200 cloud budget. Fallback if ceiling hit: drop RF-DETR bake-off (−$15-20), commit to DEIMv2 directly based on the published benchmarks.

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| `disqualifying` bucket underfit (~300 samples after thresholding) | HIGH | A/B test Poisson aux + ordinal loss focal-like reweighting; oversample in v1.5 if F1 < 0.5 |
| TAG studio → user phone domain shift | HIGH | Hand-photo benchmark in G3; if v1 gap > 30%, queue eBay scraping for v2 |
| SAM2 fails on raking-light SFX scratches/edges | MEDIUM | HITL gate in A4; auto-reject suspicious masks, hand-verify 300 |
| GroupKFold split still leaks (visual near-dups) | MEDIUM | pHash≤6 cluster groups same card variants; cert-prefix groups same submission batches |
| Blend weights (0.6/0.4) wrong for our distribution | LOW | Constrained regression on 1 331 cards; if fit poorly, fall back to literal min |
| Budget overflow (>$200) | MEDIUM | Drop bake-off → −$15-20; or reduce SAM2 to AABB-only (skip OBB classes) → save train time |

## Data sufficiency verdict

**v1 ships on current data** (67k images, 10k severity patches, 96k weak labels). One known risk:

1. **`disqualifying` severity class** — borderline. Will be measured in D3 review. If F1 < 0.5, dedicated re-scrape of TAG's "GOOD/POOR" grade tier.

**No data download needed before v1 train.** Current decision (skip DIG+, skip more TAG, skip eBay) stands. Distribution-shift risk is accepted — stakeholder bets on user photo quality + future studio-rig accessory.

## Sources of amendments (review traceability)

- cv-architect: arXiv:2509.20787 (DEIMv2), arXiv:2511.09554 (RF-DETR), arXiv:2509.18284 (modality token), arXiv:2403.04245 (dropout bias)
- data-strategist: arXiv:2510.02100 (SAM2 failure modes), arXiv:2511.13944 (GroupKFold), ForkMerge NeurIPS 2023 (aux head negative transfer)
- domain-expert: PSA Grading Standards (psacard.com/gradingstandards), TAG Score docs (taggrading.com/pages/score), Ximilar formula docs (docs.ximilar.com)

## Related

- [[../20-Areas/02-grading/defect-detection/architecture]] — March-plan (superseded by this v3)
- [[../30-Resources/adr/2026-05-24-grade-aggregation-weakest-link]] — formula ADR
- [[../30-Resources/adr/2026-05-23-grade-weights-front-65-back-35]] — front/back weighting (unchanged)
- [[../20-Areas/09-ml-research/_MOC]]
- [[../10-Projects/2026-Q2-opencv-defects]]
