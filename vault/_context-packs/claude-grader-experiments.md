---
type: context-pack
status: active
area: [grading, ml]
tags: [grading, claude, llm-grader, detector, experiments, locked]
created: 2026-06-21
updated: 2026-06-21
---

# Claude Grader — full experiment log & how to continue

> **TL;DR (locked 2026-06-21):** The MVP condition grader = **Claude Opus 4.8 vision on (whole-card image + a montage of 8 zoomed wear-zones per side)**, front/back graded separately, overall = front×0.65 + back×0.35, then a **linear calibration `grade = clip(1.58·raw − 4.88, 1, 10)`**. Validated on 100 stratified TAG cards: **CV-calibrated MAE ≈ 0.97 vs TAG, r ≈ 0.80, 73% within ±1 grade, ~$0.05/card.** Six alternative approaches were tried; **none beat the plain holistic grader**. The remaining error is the **TARGET (TAG is a noisy oracle), not the model** — every approach plateaus at ~0.97. Ship the holistic grade as a **coarse bucket** + use the **detector as an evidence/safety layer only** (NOT as a grader, NOT fed back into an LLM re-grade). Open problem = the **medium band (TAG 5–8)** and the mandatory **phone-photo gate** before deploy.

This supersedes the "v1 HRNet heatmap / segmentation" defect plans for the SHIPPING grader (those are a separate ML track). See also memory `project_claude_grader_validated`, `project_defect_research_v4`, `project_zone_classifier_confound`, `project_llm_hypothesis`.

## The pipeline (what "the grader" is)

1. **Rectify / crop** card from the orange TAG scan background — `src/claude_grade._card_box()` (bg-color segmentation; whole-card via `prep_full_card`). ⚠️ This step assumes a uniform background and **will break on real phone photos** — see Open Problems.
2. **Montage builder** `scripts/build_grade_test.py` cuts 8 labeled zones/side (4 corners 0.17·bw squares + 4 edge strips), renders a labeled montage PNG.
3. **Holistic grader** `ClaudeGrader.grade_montages()` (`src/claude_grade.py`): sees whole card + montage per side → JSON {per-side grade + 4 pillars (centering/corners/edges/surface) + worn_zones + grade_distribution + explanation}. System prompt has the calibrations: holo/foil texture ≠ defect; clean→9.5-10; use full scale.
4. **Calibration** (post-hoc, applied in scorers): `grade = clip(1.58·raw − 4.88)`. Fixes raw scale compression (model underrates gems 8.9 vs 10, overrates beat-up 6.6 vs 3.8).
5. **Detector** (`ClaudeGrader.detect_zones()`) — separate call, per-zone severity CLEAN/MINOR/MODERATE/HEAVY, precision-guarded. **Use at MODERATE+** (MINOR over-flags). Role = **evidence + safety**, not grading.

## Experiments tried (all CV-calibrated MAE vs TAG, 2-fold, n≈98–100)

| # | Approach | overall MAE | low-band MAE | verdict |
|---|---|---|---|---|
| 0 | **Holistic grader (BASELINE)** | **0.97** | 1.90 | ✅ best — locked |
| 1 | rim-crop input (tighter 0.09·bw corners, hi-res 2240px montage) | 1.16 | 2.20 | ❌ worse — context > rim-res |
| 2 | count-first severity rubric prompt | 1.11 | 1.97 | ❌ worse — over-corrects gems |
| 3 | detect→grade (severity feature → linear/isotonic map) | 1.30 | 2.03 | ❌ worse — MINOR over-flag; map can't reach low |
| 4 | hybrid min(holistic, detector) + gate | 1.01–1.06 | 1.67–1.72 | ≈ tie; small low gain, gem cost |
| 5 | **deterministic cap** (detector floors heavily-worn) | 1.04 (gated 1.00) | **1.67** | ⚠️ only thing that helps low (small) |
| 6a | routed LLM-regrade w/ MINOR-inclusive evidence | 1.29 | 2.66 | ❌ noisy evidence breaks it |
| 6b | routed LLM-regrade w/ MODERATE+ evidence | 0.98 | ~1.92 | ≈ tie overall; **fails on medium (see below)** |

Per-band baseline holistic: gem 0.84, nm 0.67, ex 0.89, **low 1.90**. Detector-as-grader is worse on EVERY band.

## Key findings (stable, trust these)

- **The ceiling is TAG, not the model.** All 7 approaches plateau at 0.97–1.30. TAG is a noisy algorithmic oracle: in our 100-set **gem & nm bands are degenerate constants** (every gem=10.0, every nm=9.0, sd=0 → 58/98 cards), **86% of TAG defect labels are on the BACK** (weighted only 0.35), **~75% of corner/edge wear is photometric-only** (invisible in flat light). So MAE-vs-TAG below ~0.8 is chasing TAG's noise, not truth. **My in-session blind grading also hit 0.97** → the montage INPUT + TAG TARGET bound it, not the prompt.
- **The model SEES the wear** (proved: a detection-framed prompt found whitening on all 8 worn zones of a card the grader called "minor"). It under-grades because (a) our anti-"cry wolf" calibration suppresses flagging, and (b) holistic grading ≠ defect scanning. NOT a vision/physics limit for flat-visible whitening.
- **Detector discriminates at MODERATE+**: gem 0.4 / nm 1.4 / ex 2.9 / low 8.7 zones. But it **UNDER-detects MODERATE wear on medium cards** (precision-tuned to stay clean on gems).
- **Feeding detector evidence back into an LLM re-grade does NOT help.** On medium cards it's **bimodal**: when the detector catches wear (e.g. 4/7 zones) the chain correctly pulls DOWN (TAG 5 → 5.3); when the detector misses (0/0, 0/2) the chain (told to "trust the inspector") pushes UP to 9–10. It missed on ~6/10 medium cards.
- **The "dangerous overclaim" count (worn→NM+) is an UNSTABLE metric** — it swings 2↔5 with tiny calibration-fit changes (threshold-sensitive near grade 7). Do NOT report it as a fine-grained win (I wrongly claimed "5→2"; it was fit noise).
- **The model's `grade_distribution` is overconfident** — 80%-mass band width ~0.53 but only **27% coverage** (TAG often outside it); on medium cards TAG is frequently entirely outside the predicted distribution. For a UI confidence band, use an **empirical ±1 grade** (~73% coverage), NOT the model's probs.
- **Medium band (TAG 5–8) is the hard core.** Moderate (not heavy) whitening in flat light is ambiguous vs texture/lighting; both holistic and detector struggle. This is where future work should focus.

## Files & data (how to re-run anything)

**Code** (all run with `./venv/Scripts/python.exe`; `ANTHROPIC_API_KEY` lives in `.env`, gitignored — ⚠️ the key pasted in chat 2026-06-21 should be ROLLED):
- `src/claude_grade.py` — `ClaudeGrader`: `.grade_montages(variant="base"|"count_first")`, `.detect_zones()`, `.regrade_with_evidence(detections,...)`, `.prep_full_card()`, `._card_box()`. Prompts: `SYSTEM_PROMPT`, `COUNT_FIRST_PROMPT`, `DETECT_PROMPT`, `REGRADE_PROMPT`. Schemas: `SCHEMA` (grade+dist), `DETECT_SCHEMA` (per-zone sev).
- `scripts/build_grade_test.py --n N --seed S --out DIR [--rim]` — stratified montage builder (4 bands gem/nm/ex/low, only truly-graded cards; writes montages + `_gt_DO_NOT_READ_until_scoring.json`). `--rim` = exp-1 tight-crop variant.
- `scripts/run_claude_grades.py --montage-dir D --n N --variant base|count_first --out F` — batch holistic grader (loads .env, ThreadPool, prints cost; builds whole-card crops).
- `scripts/run_detect.py --montage-dir D --out F` — batch Stage-A detector → detections.json.
- `scripts/run_routed.py` — the chain: holistic (from claude_grades.json) → if raw<8.5, `regrade_with_evidence` with MODERATE+ findings → routed_grades.json. (Edit `GEM_THR`.)
- `scripts/run_chain_showcase.py` — chain on 10 cards TAG∈[5,8] → chain_showcase.json.
- Scorers: `score_claude_grades.py` (vs TAG + my-blind), `score_claude_prob.py` (E[grade], band coverage, asymmetric cal), `score_detect.py` / `score_routed.py`, `cmp_runs.py --dir D` (CV-cal per-band — the main A/B tool).
- Renderers: `build_defect_report.py`, `showcase_report.py` (1-per-grade), `render_chain.py` (chain reports + distributions).
- Throwaway diagnostics were in `/tmp/` (diag.py, chain.py, tradeoff.py, consistency.py, detect_test.py) — re-create as needed; key logic captured above.

**Data / runs:**
- `runs/grade_test_100/` — **the main 100-card validation set.** Has: `montage/`, `fullcard/`, `claude_grades.json` (holistic), `detections.json` (detector), `routed_grades.json` (chain), `chain_showcase.json` (10 medium), `_gt_DO_NOT_READ_until_scoring.json`, `chain_reports/`, `CHAIN_REPORT.md`.
- `runs/grade_test_rim/` (exp-1), `runs/grade_test_cf/` (exp-2 count-first), `runs/grade_showcase/` (1-per-grade 1–10 + `REPORT.md` + `reports/`), `runs/grade_test/` (original 20-card blind test + `verdicts.json` = my in-session grades).
- Source cards: `data/tag_raw/<CERT>/images/FRONT_MAIN.jpg` / `BACK_MAIN.jpg` (+ metadata.json with grade, grade_label, surface_defects). Grade=0.0 + label=None means UNGRADED — exclude.

**Reproduce the headline number:** `build_grade_test.py --n 100 --seed 7 --out runs/X` → `run_claude_grades.py --montage-dir runs/X/montage --out runs/X/claude_grades.json` → `cmp_runs.py --dir runs/X`.

## Open problems & exact next tests (pick up here)

1. **Medium band (TAG 5–8) — the priority.** Detector under-detects MODERATE wear → chain over-grades. Try: a detector variant tuned for **recall on MODERATE without gem false-positives** (the precision/recall knob). Test with `run_detect.py` (new prompt) → `run_routed.py` → check medium cards in `chain_reports/`. Success = chain pulls TAG-5-7 cards DOWN without flagging gems.
2. **Phone-photo gate (MANDATORY before any deploy).** All MAE is on flat studio scans; `_card_box()` (orange-bg segmentation) + no-perspective-warp will fail on real phone photos, and glare reads as whitening. Need ≥30 real phone photos of known-grade cards end-to-end. If it degrades >1 bucket → ship coarse bucket + "estimate" disclaimer only.
3. **Human/PSA oracle.** TAG is noisy and its top bands are degenerate constants. **Hand-grade 20–30 cards** (or get PSA-graded ones) and re-score holistic + chain vs that — this is the ONLY way to learn the true ceiling vs TAG noise. Until then we're tuning against noise.
4. **Recalibrate** `1.58/−4.88` on a larger N (it was fit on 100; CV-stable but loose CI).
5. **Decision metric**, not exact MAE: 3-bucket (GEM+/MID/PLAYED) was 78% exact / 99% within-1-bucket. Track that + a recall-on-played safety metric instead of MAE-vs-TAG.

## Locked product decision (until the above changes it)

- **Grade number** = holistic grader + `clip(1.58·raw−4.88)`, presented as a **coarse bucket** + empirical **±1 band**.
- **Detector @ MODERATE+** = **evidence layer** (show the user WHERE the wear is) + optional **deterministic safety cap** (floor obviously-heavy cards). NOT an LLM re-grade.
- **Centering** = geometry (separate module), NOT this grader; and per `project_defect_research_v4`, centering is ~null for TAG grade — display it, don't grade on it.
- Do **not** re-run prompt-wording A/B loops (converged). Next real levers = INPUT (only via better capture, e.g. multi-angle), TARGET (human oracle), and the medium-band detector-recall knob.
