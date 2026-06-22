---
type: project
status: active
area: [grading, api, webapp, product]
tags: [pregrading, decision-card, centering, claude-grader, TZ, integration]
created: 2026-06-22
updated: 2026-06-22
---

# TZ — Pregrading integration (Centering + Claude condition grade + report)

> **Goal:** ship the **Pregrading / Decision Card** flow into the live product — user uploads a card, we (1) measure CENTERING (geometry, user-confirmed) and (2) estimate CONDITION via the Claude grader, then show a **report**: a grade RANGE + per-pillar + WHERE the wear is + a text description. This is the differentiating sell-vs-grade flow the UX audit found missing ([[../20-Areas/11-product/_MOC|product]], `project_ux_decision_audit`). The grading R&D is DONE and LOCKED — see [[../_context-packs/claude-grader-experiments]]; this project is INTEGRATION only.

## Agreed scope (decided with stakeholder 2026-06-22)
1. **Architecture:** Base44 webapp (UI) → **our FastAPI backend** (Hetzner `src/api.py`) runs centering + Claude grader (Python + `ANTHROPIC_API_KEY`). Webapp never runs the grader directly.
2. **Grade output = a confident empirical PROBABILITY DISTRIBUTION over grades + a most-likely grade + bucket.** E.g. "Most likely **EXCELLENT · 6**" with `6:40% 5:30% 4:20% 7:10%`. **Confident voice — never "low confidence / recommend a professional" as an apology** (it undermines the product). Uncertainty is expressed BY the distribution width, not by a hedging sentence. The distribution is built from our **measured residual error per grade-level (empirical), NOT the model's own `grade_distribution`** (which is overconfident — coverage 27%). Light "estimate from photos, not an official PSA/BGS/CGC grade" footer is fine; "grade it" only ever appears as a confident ACTION (and grading is the desired sell-vs-grade outcome / future affiliate), never as "we couldn't tell." Honors brand two-grade spirit ([[../_context-packs/brand-positioning]]).
3. **Both FRONT and BACK are MANDATORY** — a full grade requires both sides (back drives a real share of condition). No single-side grade.
4. **Centering UX = interactive:** auto-detect borders, user can drag to confirm (reuse `static/centering.html` logic). Human-in-loop supplies the final precision.
5. **Cost/gating:** grading runs through the **existing subscription + per-grade-limit system** (Stripe + Base44 entities). To be refined separately; this TZ just calls the gate.

## User flow
1. Upload **front AND back** (both REQUIRED — block grade until both present).
2. **Centering step (interactive):** backend rectifies + proposes border lines → webapp shows draggable overlay → on confirm, backend computes L/R & T/B ratios per side.
3. **Condition step:** backend builds the 8-zone montages + whole-card crops → Claude grader → calibrated grade + per-pillar + detector evidence.
4. **Report screen (the Decision Card):** grade RANGE + bucket + 4 pillars + centering ratios + "wear found here" (zones) + text explanation + disclaimer + sell-vs-grade hint.

## Backend tasks (FastAPI, `src/api.py` + `src/`)
- **B1. New `/grade` endpoint** — port `src/claude_grade.py` (already built & validated) behind FastAPI. Input: front AND back (both required). Steps: `build montage (8 zones/side)` + `prep_full_card` → `ClaudeGrader.grade_montages()` (holistic) + `ClaudeGrader.detect_zones()` (evidence). Apply **calibration `grade = clip(1.58·raw − 4.88, 1, 10)`** to get the most-likely grade Ĝ. Init the grader at startup from `ANTHROPIC_API_KEY` env (mirror the dead Gemini init; ⚠️ Gemini-key-in-code is the anti-pattern — env only).
- **B1b. Empirical grade DISTRIBUTION** (the headline output) — do NOT use the model's `grade_distribution` (overconfident, 27% coverage). Build it from our measured residual error: a discretized distribution centered on Ĝ with σ from the grade-level band, binned by **predicted Ĝ** (not TAG band — at inference we only know Ĝ). ✅ **σ DERIVED 2026-06-22** (`scripts/derive_sigma.py`, on `runs/grade_test_100`, same 2-fold CV calibration as `cmp_runs.py`; output `runs/grade_test_100/sigma_table.json`). The earlier 0.9/1.1/1.8 were per-band MAE reused — WRONG. **Locked table (σ of calibrated residual):**

| band | range | n | **σ** |
|---|---|---|---|
| high | Ĝ ≥ 8.5 | 52 | **0.69** |
| medium | 5.5 ≤ Ĝ < 8.5 | 39 | **1.76** |
| low | Ĝ < 5.5 | 7 | **1.52** (sparse → floor at overall σ 1.32) |

Calibration verified honest: claimed-vs-actual P(TAG within ±1) matches per band (high 92/94%, medium 46/49%, low 53/57%). Note medium is genuinely wide (±2, not ±1) — the distribution must SHOW that, don't fake confidence. Then build the dist: discretize on the half-grade grid, **truncate to [1,10] and renormalize** to sum 1.0, round to display %. Re-derive σ whenever the calibration coefs or validation set change. Output `[{grade, prob}]` over a window around Ĝ (probs sum to 1, rounded to nice %). Most-likely grade + bucket derived from it. This gives a CONFIDENT, calibrated distribution (TAG lands where we say ~73%+ of the time), not a hedge.

> **Coverage fix 2026-06-22 — `top_k=5` (σ UNCHANGED).** Measuring the *production* `build_overall` output end-to-end (new `scripts/score_empirical_coverage.py`, on the **sides-weighted** 0.65/0.35 aggregation the endpoint actually calibrates) showed the rendered band covered TAG only **65%** at the original `top_k=4` — under the ≥73% promise. Root cause was the **rendering width, not σ**: at medium σ≈1.8 four half-grade bars span only ~44% of mass. Fix = `build_overall` now renders **`top_k=5` bars** (`src/pregrade_distribution.py`), which lifts production coverage to **77%** (high 93% / medium 54% / low 62%). **σ was deliberately left as the table above** — re-deriving σ on the sides-weighted aggregation gave near-identical values (`{0.77, 1.83, 1.58}`, overall 1.35) and `derive_sigma`'s claimed-vs-actual check confirms the current σ is honest (even slightly conservative on medium); widening σ to chase the 73% number tested *ineffective on top of top_k=5* and would have been dishonest, so it was rejected. Bucket GA metrics are unaffected by `top_k`: **78% exact 3-bucket** (GEM+/MID/PLAYED), PLAYED-recall 33% (0 overclaimed to GEM+) — see `scripts/score_buckets.py`. Residual gap is the medium band (54%), a real flat-light limitation, not a distribution bug → fix via the medium-band detector-recall work (B2 / context-pack open problem #1), not wider σ.
- **B2. Detector = evidence/safety only.** Use `detect_zones` at **MODERATE+** for the "wear found here" list (gem 0.4 / low 8.7 zones — reliable; MINOR over-flags, ignore it). Do NOT feed detector findings back into an LLM re-grade (tested, fails — see context-pack). Optionally a deterministic safety floor (if a side has ≥6 MODERATE+ zones → cap that side ≤5).
- **B3. Centering endpoints already exist** (`/centering`, `/centering/compute`, `/centering-ui` in `api.py`, geometry in `src/card_detector.py`). Confirm they return: rectified card + proposed border lines + computed L/R, T/B ratios per side. Extend if the contract below needs fields. NOTE: per `project_defect_research_v4`, centering is ~null for TAG grade — **display the ratio as a measurement; do not let it dominate the grade.** Authoritative centering = geometry; condition pillars (corners/edges/surface) = Claude.
- **B4. Subscription/limit gate** — `/grade` checks the user's plan + remaining grade-credits (existing system) before spending the Claude call; 402/limit response when exhausted.
- **B5. Cost/perf:** ~$0.05/card, ~10-15s latency (Claude vision + detect = 2 calls). Stream/async-friendly; return a job result, not a 30s block. Cache montages by image hash.

## Output contract (`/grade` response)
```json
{
  "is_estimate": true,
  "footer": "Estimated condition from your photos — not an official PSA/BGS/CGC grade.",
  "overall": {
    "most_likely": 6.0,
    "bucket": "EX",
    "label": "Excellent",
    "distribution": [ {"grade":6,"prob":0.40}, {"grade":5,"prob":0.30}, {"grade":4,"prob":0.20}, {"grade":7,"prob":0.10} ]
  },
  "front": { "grade": 7.5, "centering": 8, "corners": 7.5, "edges": 7, "surface": 8.5, "worn_zones": ["LEFT","RIGHT"] },
  "back":  { "grade": 7.0, "centering": 8, "corners": 7,   "edges": 7, "surface": 8,   "worn_zones": ["TR","BL"] },
  "centering": { "front_lr": "55/45", "front_tb": "52/48", "back_lr": "60/40", "back_tb": "53/47" },
  "evidence": { "front": {"TL":"CLEAN","TOP":"MODERATE", ...}, "back": {...} },
  "explanation": "Holo surface clean (not damage). Light edge whitening on the back left/right...",
  "decision": "sell_raw | grade_it"   // confident action; grade_it when most_likely bucket is NM+ on a card worth grading
}
```
Buckets: GEM ≥9.5 / MINT 9–9.5 / NM 8–9 / EX 5.5–7.5 / PLAYED <5.5 (tune labels with product). `distribution` is the headline (render as bars); `most_likely` + `bucket` lead the card.

## Frontend tasks (Base44 webapp, `CardChecker_MVP`)
> ✅ **ROLLOUT DECIDED 2026-06-22 = Variant B (new flagged route).** Build the new pregrading as a **separate route behind a feature flag** (beta/us only); the existing live `ConditionCheck.jsx` → `/gemini/grade` flow stays UNTOUCHED for the ~10 live users until the new one is validated on ≥30 real phone photos, then we flip everyone and retire the old screen. Do NOT refactor the live page now.
>
> **New route is a MULTI-STEP wizard, in this order:** (1) **Upload** front AND back (both required) with explicit quality guidance — sharp/in-focus, card perpendicular to camera (no tilt), good even lighting, fill the frame; → (2) **Interactive centering** (the centering feature opens here, draggable border confirm); → (3) **Claude condition grade** → (4) **Decision Card**.
>
> Note for the eventual cutover: the old screen still ships the banned copy — `Report.jsx:314-321` "consult certified grading services (PSA/BGS/CGC)", a `{confidence}%` Badge, `cardcheckApi.js` "Low confidence (X%)" — and `GradeDistribution.jsx` hardcodes grades [6..10] (can't render a PLAYED card). The NEW route must not reuse those; build a fresh distribution component on the B1 contract. Keep a kill-list of those strings for when the old screen is retired.
- **F1. Upload UI** — front AND back (BOTH required; disable "Grade" until both present), with photo-quality hints (well-lit, flat, fill frame). ⚠️ See Risks — phone-photo crop is the weak link.
- **F2. Interactive centering** — render backend's proposed border lines over the rectified card; draggable; "Confirm" → POST to `/centering/compute`. Port the interaction model from `static/centering.html` into the webapp's stack.
- **F3. Report / Decision Card screen** — lead with **most_likely grade + bucket** ("Most likely · Excellent · 6"), then the **distribution as bars** (`6:40% 5:30% 4:20% 7:10%`) — confident, no hedging copy, NO "low confidence / see a professional" line. Then 4 pillars per side; centering ratios; **"wear we found"** list/overlay (from `evidence` MODERATE+ — the hero, brand = "decide with data"); the text `explanation`; the confident `decision` (sell-vs-grade); a light `footer` disclaimer. See the approved mockups in the project discussion (3 examples: Mint / Excellent-distribution / Played).
- **F4. Gate UX** — show remaining grade-credits; upsell when limit hit (ties to existing subscription).

## Constraints / non-goals
- NOT an official grade — always show the empirical distribution + light footer (never a bare single precise number, never a hedging "we're unsure" sentence). Confident voice.
- Both sides REQUIRED — no single-side grades.
- Do NOT re-run prompt-wording A/B or re-add the dead Gemini grader. The grader is LOCKED.
- `mobile/` is dead — webapp only.
- Deploy safety: NEVER deploy untested code / beyond intended files; use the vault deploy procedure, not `deploy.sh` ([[../20-Areas/10-infrastructure/deploy-safety-rules]]).

## Acceptance criteria
- End-to-end: upload front AND back on the webapp → see centering → confirm → get the Decision Card (most-likely grade + bucket + distribution bars + pillars + evidence + explanation + decision), gated by subscription.
- `/grade` returns the contract above; calibration applied; **empirical distribution** (not the model's self-probs); detector evidence at MODERATE+; subscription/limit enforced; rejects single-side requests.
- On a clean card → distribution concentrated high ("no significant wear"); on a worn card → distribution lower + worn zones shown. (Sanity, not a precision claim.)
- Confident voice everywhere — no "low confidence / see a professional" copy; footer disclaimer present; no bare single precise grade.

## Risks / explicitly OPEN (carry from R&D — see context-pack)
- **Phone-photo distribution shift (BIGGEST):** all validation (MAE 0.97) is on flat studio TAG scans. `_card_box` (orange-bg segmentation) + no perspective-warp **will mis-crop real phone photos**; glare reads as whitening. → Add a **photo-quality gate** (blur/glare/quad-confidence → "retake") and, until validated on ≥30 real phone photos, keep the **range wide + disclaimer prominent**. This is a pre-GA gate, not a blocker for an internal/beta rollout.
- **No ground-truth oracle:** we only know agreement-with-TAG (noisy), not true accuracy. Treat the grade as a beta estimate.
- **Medium band (TAG 5–8) is the least reliable** (moderate wear ambiguous in flat light). The range absorbs this.
- **Security:** keep the existing `ANTHROPIC_API_KEY` (stakeholder controls it, decided 2026-06-22 — not rolling). Hard rule: backend **env only**, never in code / client / logs / git.

## Implementation status — 2026-06-22 (branch `feature/pregrading-grade-endpoint`, pushed; NOT deployed)
Built this session (5 dev-agent verify → build); all this-repo work tested, nothing deployed, no live flow touched.
- **B1/B1b DONE** — `/grade` endpoint, calibration, empirical distribution. **top_k=5** (raises rendered-band coverage 65%→77% to honor the ≥73% promise; verified via `scripts/score_empirical_coverage.py`, which now reads the real production bar count).
- **B2 DONE** — detector evidence MODERATE+ only; deterministic one-way safety floor (≥6 MODERATE+ zones → that side ≤5) in `pregrade_service.assemble`.
- **B4 DONE (server-side enforcement)** — `src/grade_gate.py`: shared-secret auth (`X-Grade-Secret` + `X-User-Id`), atomic per-user credit decrement, 402 on exhaustion, global daily-cap (429), per-user rate limit, content-hash idempotency, refund-on-failure. Ledger in a **separate `data/grade_credits.db`** (never the catalog). Env: `GRADE_API_SECRET`/`GRADE_FREE_CREDITS`/`GRADE_RATE_PER_MIN`/`GRADE_DAILY_CAP`. **Still OPEN:** sync this ledger with Base44/Stripe as the product source of truth (seam = `grade_gate.grant()`); roll the leaked key (user owns).
- **Error handling DONE** — Anthropic errors → 429/504/503/502; SDK 90s timeout.
- **Centering — RESOLVED: stays SEPARATE.** `/grade` does NOT carry centering; the webapp composes the Decision Card from `/grade` + `/centering/compute`. Compute contract: request `{outer,inner}` (canvas-px L/R/T/B each), response `{lr:[L,R], tb:[T,B], worst_axis_offset_pct}`. (Supersedes the `centering` block shown in the Output contract above.)
- **Latency — RESOLVED: synchronous-with-timeout for beta** (awaited ~10–15s response, not a poll-job). Revisit poll-job only if traffic demands.
- **Frontend DONE (beta)** — new flagged `/Pregrade` route in `CardChecker_MVP` (admin-role gated, not in nav): wizard (front+back required → CenteringStage React-port → ~15s condition → DecisionCard), `DecisionDistribution` ({grade,prob} fraction, full 1–10, aria), `EvidenceOverlay` (8-zone grid), `gradeCardV2`/`confirmCentering` (402→UpgradeModal, AbortController). `ConditionCheck.jsx`/`Report.jsx` untouched; Vite build green.
- **Metrics** — 3-bucket (GEM+/MID/PLAYED) **78%** exact, PLAYED-recall 33% but ZERO PLAYED→GEM overclaim (`scripts/score_buckets.py`). Medium-band coverage 54% remains the flat-light weakness → detector-recall work, not σ.
- **Remaining before GA:** full Docker rebuild (anthropic dep pinned ✓, image not rebuilt); paid golden-regression through `/grade` (~$5); ≥30 real-phone-photo gate calibration; Base44↔ledger credit sync; CORS lock + roll key; rollback-plan capture.

## References
- Grading R&D (everything tested, all scripts/data/commands): [[../_context-packs/claude-grader-experiments]]
- Code: `src/claude_grade.py` (grader+detector), `src/card_detector.py` + `static/centering.html` (centering), `src/api.py` (FastAPI), `scripts/run_claude_grades.py` (batch ref).
- Memory: `project_claude_grader_validated`, `project_defect_research_v4` (centering≈null for grade), `project_brand_positioning` (two-grade rule), `project_ux_decision_audit` (Decision Card missing), `project_real_product_state` (Base44 webapp target).
