---
type: session
status: active
area: [grading, pricing, api, webapp, product, infrastructure]
tags: [pregrading, pricing, launch-readiness, deploy, billing]
created: 2026-06-30
updated: 2026-06-30
---

# Session 2026-06-29/30 — Pregrading live iteration + pricing overhaul + launch-prep

TL;DR: Shipped pregrading (Quick Pregrading) to closed beta, iterated heavily on live stakeholder feedback (grading logic overhaul + 16 corner/edge crops + zoom lightbox + UX), fixed the credit-window bug, overhauled price coverage (US market 8%→88% EN), hardened deploy, verified billing. Remaining for public launch: grade accuracy validation (D1/D2, balance now topped up) + privacy/terms + final QA + Base44 publish.

## What's DONE (deployed to prod `bees.cardchecker.app`, rebuilds #1–#9 + pricing rebuild)

**Pregrading `/grade` — LIVE (closed beta, admin-only).** Backend branch `feature/pregrading-grade-endpoint` (pushed, NOT merged to main — origin/main lacks the grade commits). Key pieces:
- `src/grade_gate.py` — auth+billing gate (shared-secret OR Base44 token; atomic credit ledger `data/grade_credits.db`; 402/429/rate-limit/idempotency/refund).
- `src/base44_auth.py` — verify Base44 JWT via REST `me`, enforce per-tier limit against the Base44 `CreditTransaction` ledger, charge-after-success. **Calendar week/month windows (match webapp), NOT rolling.** **Admins are UNMETERED** (role==admin bypasses the limit — internal testing). `GRADE_REQUIRE_BASE44=1` (prod) + `GRADE_BETA_ADMIN_ONLY=1`.
- **GRADING LOGIC (superseded the locked TAG-calibration approach, stakeholder-directed):** WEAKEST-LINK aggregation (PSA/BGS, not average; one bad subgrade caps the card), TAG calibration `1.58·raw−4.88` DROPPED for display (`calibrate()` kept for future PSA recal), centering subgrade from GEOMETRY (`pd.centering_grade_from_offset`), graded whitening cap (`_whitening_cap`: 1 MOD+→9, 2→7, 4→5, HEAVY harsher), back loses front-primary `BACK_LENIENCY` when it has confirmed MOD+ whitening, integer PSA distribution (sums to 100%), tightened display σ (medium→1.0). Gate philosophy: ALWAYS inspect (detector free/concurrent), cap on detector–holistic DISAGREEMENT (not skip-on-9-10). Surface stays in holistic grade but NOT zone-localized. No glare-check (stakeholder accepted FP risk). Code: `src/pregrade_distribution.py`, `src/pregrade_service.py`. ~90 tests green. **DO NOT revert to average/TAG-calibration.**
- **Crops from USER-confirmed centering geometry** (rectified card + dragged outer box, both sides) → precise corner/edge crops + fixes phone-photo crop + detector recall. `/grade` takes `front/back_warped_url` + `front/back_outer`. Report shows 8 corners + 8 edges with severity badges + a zoom lightbox (edges open full-strip). `montage._extract_zones(box=...)`.
- OverloadedError(529)→503 + 60s client timeout.

**Webapp (CardChecker_MVP, merged to main):** new `/Pregrade` route = "Quick Pregrading" (admin-gated wizard: upload→centering both sides→condition→Decision Card). "Detailed Pregrading" = greyed coming-soon teaser (ReportNew.jsx). Banned copy purged everywhere ("low confidence"/"consult PSA/BGS/CGC"/confidence%). Note: **Base44 auto-commits package bumps to main on Publish → `git pull` before pushing.**

**Pricing overhaul (deployed):**
- Display freshness bug FIXED: `/prices` last-row-wins clobbered fresh poketrace with stale March CSV → now freshest-wins (`setdefault` + csv tiebreaker in `src/api.py`). CardMarket shows current price again.
- US-market ingestion FIXED: PokeTrace US is keyed by `tcgplayer_ids` (NOT cardmarket_ids). New `update_poketrace_us` Step 1b in `scripts/update_prices_daily.py`. Ran it → **TCGplayer 8%→88% EN, eBay 3%→84% EN**. Daily cron keeps it fresh. `PT_LIMIT/PA_LIMIT` env-overridable.
- Coverage ceiling: ~1,424 cards (TW sets, JP/EN promos/trainer-kits) are GENUINE PokeTrace absences — not fixable via PokeTrace; live links cover them. JP/TW have no US prices (no tcgplayer_id, structural). `prices_external` grows ~422K rows/day, no pruning → needs retention eventually (operational, not urgent).

**Deploy reliability:** `scripts/deploy_prod.sh` (detached build survives SSH drops + rollback tag + smoke); `deploy.sh deploy` deprecated → points to it. ⚠️ SSH to prod drops mid-build during heavy installs → ALWAYS deploy detached (nohup) + poll a log file.

**Billing verified (E):** path wired (createSubscriptionCheckout → Stripe → verifySubscription → tier). Stripe price-ids LIVE + match UI: Plus €6.99/mo, Pro €14.99/mo. Only a real test-purchase left to 100%-confirm round-trip.

## REMAINING for public launch
- **D1/D2 (grade accuracy) — balance topped up 2026-06-30, RUN NEXT.** Golden regression of the NEW weakest-link logic on `runs/grade_test_100` (paid ~$5) — currently only validated on a 10-card faithful TAG test (`scripts/test_beta_tag.py`, MAE 1.00; weaknesses: lenient on heavily-played + front detector over-flags on holo). Scale to 100 + compare 2–3 detector severity-threshold variants. This decides whether Quick Pregrading opens beyond admins.
- **F:** privacy/terms (verify real, not placeholders — needed for store), final QA across all screens, then publish via Base44 (Base44 packages the webapp for Play/App Store automatically).
- **Validation gate:** ≥30 real phone photos before opening to non-admins.
- **Optional/deferred:** CORS lock /grade to webapp origin (token already protects budget); recall tuning; CardMarket CSV refresh for ~26 EN CSV-only cards; prices_external retention.

## Handoff / next action
Balance is topped up → run **D1/D2** (golden regression on 100 cards + detector variants). Then **F** (privacy/terms + final QA + Base44 publish). Stakeholder still needs to click **Publish on Base44** to surface the merged frontend (Quick Pregrading + crops + lightbox + copy purge). See memory [[project_pregrading_integration]], [[project_pricing_sourcing_strategy]], [[reference_base44_app_and_credits]], context-pack [[claude-grader-experiments]].
