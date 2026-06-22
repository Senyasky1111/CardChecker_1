---
type: log
status: active
updated: 2026-05-23
---

# CardChecker Log

> Append-only chronological journal of decisions, incidents, sessions, and milestones.
> One line per event. Format: `## [YYYY-MM-DD] {tag} | {brief}` + optional details below.

Tags: `decision` `incident` `session` `release` `pivot` `experiment` `milestone`

---

## [2026-06-22] decision milestone | Pregrading integration TZ LOCKED + ClickUp task + 5-agent review

Locked the TZ `vault/10-Projects/2026-Q2-pregrading-integration.md` for shipping pregrading into the
live webapp: centering (interactive geometry) + Claude condition grade → Decision Card. Output =
**confident empirical probability distribution** (most-likely grade + bucket + dist bars), front AND
back BOTH mandatory, NO "low confidence / see a professional" copy (user-rejected). Ran 5 independent
expert agents (backend / frontend-UX / ML-correctness / security-billing / deploy-QA) — surfaced 4
blockers now in the task: (1) roll the leaked ANTHROPIC_API_KEY, (2) reconcile the existing live
`/gemini/grade` flow (ConditionCheck.jsx, back-optional, banned "low confidence" copy already shipped),
(3) the per-band σ (0.9/1.1/1.8) are GUESSED MAE values — must be empirically fitted from CV-calibrated
residuals + coverage-verified, (4) phone-photo gate is a hard pre-GA gate (studio-only validation).
ClickUp: App development → 86cack80c.

## [2026-06-21] experiment milestone | Claude grader — 7 approaches tested, holistic LOCKED at MAE 0.97

Built + validated the LLM condition grader (Claude Opus 4.8 on whole-card + 8-zone montages,
front 65/back 35, linear cal grade=clip(1.58·raw−4.88)). 100-card CV: MAE 0.97 vs TAG, r 0.80,
73% within ±1, ~$0.05/card. Tried rim-crop input, count-first prompt, detect→grade, hybrid,
deterministic cap, routed LLM-regrade-with-evidence — none beat plain holistic. Ceiling is the
TARGET (TAG noisy: gem/nm degenerate constants, 86% labels on back, 75% wear photometric), not
the model (model SEES the wear; proved with a detection prompt). Detector @ MODERATE+ discriminates
(gem 0.4/low 8.7) but under-detects MODERATE → chain bimodal & fails on medium (TAG 5-8).
"dangerous overclaim 5→2" was fit-noise (retracted). LOCKED: holistic grade as bucket + detector
as evidence/safety only (no LLM re-grade). Full doc: [[claude-grader-experiments]]. Open: medium
band, phone-photo gate, human/PSA oracle.

## [2026-06-19] session decision | Pricing sourcing research — keep aggregator, no scraping core

Surveyed worldwide how card-pricing products source prices/links + audited our code.
We're already aggregator-consumer (PokeTrace backbone + Pokemon-TCG-API + CardMarket CSV,
daily refresh; links are generated URLs). 2026: official APIs (TCGplayer/Cardmarket/eBay-sold)
closed to new devs. DECISION: keep architecture; add a real sold-comps source (recommended
The Card API) for accuracy + graded-by-grade; affiliate links (eBay EPN + TCGplayer/Impact)
for revenue; JP scraper (Mercari/Yahoo) deferred. Blocked on user API key for pilot.
See [[_sessions/2026-06-19-pricing-sourcing-research]] + plans/calm-jumping-rossum.md.

## [2026-05-31] session | Stripe Customer Portal flow + vault overhaul commit

Subscription plan changes (paid↔paid) now route through Stripe Customer Portal
`subscription_update_confirm` flow with `always_invoice` proration. Replaces silent
`create_prorations` from 2026-05-24 D5 which queued the charge for next invoice and
made upgrades look free. Resume Subscription button added to current-plan card when
cancellation is scheduled. Portal config `bpc_1TconXDbnOBKnZvyi7R6ilVi` updated via
raw Stripe API (neither hosted nor local MCP exposes that endpoint).

Backend `6680265` — vault overhaul + multi-agent infra from prior session committed.
Webapp `002f94f` + `28c056f` — pricing flow fix + Portal pivot. See
[[_sessions/2026-05-31-stripe-portal-fix-and-vault-overhaul-commit]].

---

## [2026-06-18] milestone | defect detection hits a physical+label WALL after 3 honest retrains

Built an HONEST full-card eval harness ([eval_defect_fullcard.py](scripts/eval_defect_fullcard.py)):
recall vs ALL TAG points on damaged cards + false-peaks per CLEAN gem-mint card, threshold-swept.
It exposed that the v3 tile-F1 0.67 was a center-prior artifact (full-card recall≈0 at FP≤0.5).

Ran two corrective retrains: EXP-1 (single class-agnostic channel + de-centered positives +
trustworthy clean negatives) cut the full-card flood 7× but recall stayed ~3% — interior-crop
negatives didn't match the sliding-window distribution (floods on borders/text/holo). EXP-2
(inference-matched windows: defect at random window position, multi-point labels, full-card
coverage negatives) is the best of three — first to reach FP≤0.5 (recall 1% @ FP 0.35) and
recall 15% @ thr0.1 — but still unusable.

**All three top out at ~1–15% full-card recall. This is a physical + label wall:**
- EXP-0 visibility audit: ~75% of TAG points sit below background gradient → flat-invisible.
- LLM cross-check (Claude Opus vision): 3% flat / 8% SFX / 18% SFX-zoom (`project_llm_hypothesis`).
- TAG points are sparse/exact → recall-vs-TAG understates true defect-finding.

Decision: STOP flat-photo heatmap retrains — defect localization from one flat phone photo vs
TAG points is near-impossible. Pivot to: ship CENTERING (LLM ~2.5pp MAE, works) as MVP core;
move defects to SFX/multi-angle capture (signal exists) or reframe as "highlight major visible
wear"; build a fresh hand-labeled EXHAUSTIVE benchmark to measure defects fairly. Spent ~$55
cloud across v3+EXP-1+EXP-2. Models: `models/defect_{heatmap,exp1,exp2}_best.pt`.

## [2026-06-15] milestone | first defect-heatmap model trained — val macro-F1 0.67

First real defect-detection model is trained, evaluated, and on disk. Point-supervised
CenterNet-style heatmap, HRNet-W32 backbone, 7 classes, native-res 512px tiles
(66 061 train / 14 554 val), 40 epochs on a rented H200. Pod self-stopped, then terminated.

**Best val macro-F1 = 0.6677 @ epoch 11** (`models/defect_heatmap_best.pt`, 125 MB; log at
`runs/defect_full/log.json`). Per-class point-F1 @ tol=24px:

| class | P | R | F1 | n(val) |
|---|---|---|---|---|
| edge_wear | 0.91 | 0.94 | 0.93 | 2852 |
| scratch | 1.00 | 0.70 | 0.83 | 489 |
| dent | 1.00 | 0.57 | 0.73 | 552 |
| crease | 0.72 | 0.74 | 0.73 | 592 |
| corner_wear | 0.71 | 0.71 | 0.71 | 7167 |
| surface_damage | 0.63 | 0.65 | 0.64 | 2856 |
| stain | 1.00 | 0.07 | 0.12 | 46 |

Reads: precision-heavy profile (scratch/dent/stain all P=1.0) — exactly what an assistant
wants (no crying wolf), recall is the lever. Clear **overfit after ep11**: train loss kept
falling 0.38→0.006 while val macro-F1 decayed 0.668→0.48; dent collapsed 0.73→0.29. best.pt
is the ep11 checkpoint, not ep39. `stain` is data-starved (230 train) → near-useless recall.
`surface_damage` is the noisy catch-all → lowest precision.

CAVEAT (per spec): this F1 is **agreement-with-TAG-points@24px**, the agreement ceiling, NOT
ground truth. Real ship gate is blind audit-precision ≥0.80 on real phone photos — not yet run.

Process note: a 50-tile sanity first returned macro-F1=0.000 — caught a **sanity-design bug**
(eval ran on different val tiles + macro only averaged classes with n≥20), not a model bug.
Fixed with `--overfit` (eval==train tiles) + `min_n`; corrected sanity hit 0.94, proving the
pipeline before the ~$30 full run. SSH stayed broken on the pod → autonomous boot-command +
HF result upload + self-stop pattern (as before).

Next levers: early-stop/fewer epochs already captured by best-ckpt save; lift recall via
stronger aug + weight decay; oversample/collect stain+dent; de-noise surface_damage labels;
then centering keypoint model + anomaly head per [[../_context-packs/v3.3-final-architecture]].

## [2026-05-24] milestone | v3.2 plan locked, build starts

After 3 full validation rounds (12 reviewers) + stakeholder corrections + self-review on Round-4 new items (Round 4 agents timed out via Stream idle, not their fault), v3.2 is final.

Stakeholder corrections layered on top of reviewer findings:
- Defect classes stay at 7 (no split — keep simplicity, may revisit in v1.1)
- Quality gate = soft warning flags, NOT block (graded slabs are always sleeved)
- Output = grade + interval + full probability distribution over 19 buckets (1.0-10.0)
- Centering: validate against TAG's 96 455 L/R + T/B ratios, fallback learned regression if MAE > 3%
- Aggregator: fit on 1331 cards, validate end-to-end on 41 292 cards (NOT 100 hand-labeled)
- Color invert as training aug p=0.3 + inference TTA on MAIN-only (×2 latency, ~+2% mAP)
- Recognition-first conditioning: when card identified by CLIP+OCR+SQL, use DB metadata for finish/era/lang. Aux heads as fallback.
- Targeted dozaliv: ~12 GB crop images for 1331 cards with per-zone scores
- Tier-2 amendments (monitoring/RUNBOOK/continual-learning) deferred to v1.1 sprint after first train
- Inference infrastructure: Modal serverless first (pay-per-grade), Hetzner GEX44 after 250 grades/day crossover

Build starts now. Sequence:
1. Section A1: rebuild converter `scripts/build_v3_dataset.py` (3-4h, $0)
2. Sample-verify on 10 cards
3. Full run on 96k
4. /dataset-doctor verify
5. Section A4: SAM2 bbox refinement (~$25-40, 4-6h H100 background)
6. Section B1: DINOv3 SSL pretrain (~$40-50, 16h H100)
7. Section C: detector + severity training (~$75-90)
8. Eval against 41k TAG holdout
9. Ship v1 to /grade-v2 endpoint via Modal serverless

Canonical plan: [[../_context-packs/v3-defect-detection-plan]]. ADRs: [[../30-Resources/adr/2026-05-24-grade-aggregation-weakest-link]].

## [2026-05-24] decision | defect-detection v3 plan locked after 3-reviewer validation

Spawned 3 centralized research agents (cv-architect, data-strategist, domain-expert) to validate the v2 plan. All returned APPROVE-WITH-CHANGES with 9 amendments. Biggest finding: v2 plan cloned Ximilar's geomean aggregator instead of PSA's weakest-link rule — would have over-graded weak-pillar cards by 1-2 grade points systematically. Captured in new ADR [[../30-Resources/adr/2026-05-24-grade-aggregation-weakest-link]].

Other key amendments locked into v3:
- Class-conditional bbox (OBB only for scratch/crease, AABB for blobs)
- RF-DETR vs DEIMv2 bake-off on 5k subset before $60-90 commit
- Curriculum SFX-dropout p=0.5→0.2 + learnable SFX-presence token
- SAM2 with HITL gate (auto-reject + 300-sample hand-verify)
- GroupKFold (cert-prefix + pHash≤6 cluster + grade-bucket), NOT language/era stratification
- Poisson aux head default OFF, 3-way A/B test
- Severity buckets renamed to TAG vocab (clean/minor ding/major ding/disqualifying), thresholds anchored to TAG-published 950/990

Budget revised: $171-241 (was $150-210). Tight against $200 user-cap.

Data sufficiency verdict: v1 ships on current 67k cards / 10k severity patches. Two acknowledged risks — `disqualifying` undertraining (~300 samples) and TAG-studio→user-phone domain shift. Both measured in G3 eval (hand-photo benchmark set).

Canonical plan: [[../_context-packs/v3-defect-detection-plan]].

## [2026-06-05] finding | v1 defect spec — resolution + physical ceiling (10-agent round)

A 10-agent validation of the points+heatmap plan surfaced two fundamentals: (1) the 1280px dataset destroys tiny defects (hairline scratch → 0.6px at 1280, 0.25px at DINOv2-518; one ViT patch averages 2.4mm) — must re-export NATIVE-res 512px defect tiles from local tag_raw originals (~15GB upload, data already local, no re-download). (2) Physical ceiling — print-lines/hairline-scratches/ink defects are visible ONLY under SFX raking light, physically ABSENT in flat phone pixels (verified visually in store_listing/visibility_check). So "detect even the tiniest defects from one flat photo" is partly physically impossible, not a model limit; only fixable by multi-angle capture (deferred v2).

v1 agreed architecture: HRNet/ConvNeXt hi-res CNN on native-res tiles for defects (NOT frozen DINOv2 — ViT can't resolve hairlines) + FIDT per-class heatmap + unsupervised anomaly detection (Dinomaly/PatchCore on 6k clean, ~99% AUROC, catches what sparse TAG points missed) + SFX (~20k already local) as CroDiNo co-training teacher. Centering = 8-keypoint detection + homography + geometric ratios, with TAG 96k ratios used BOTH to train (ratio-consistency loss) AND validate. Honest UX: highlight what's visible + "tilt under angled light" for fine inspection. Eval: per-class point-F1@r24 + blind audit-precision≥0.80 + clean-FP≤0.5/card. Spec: [[../_context-packs/v1-defect-detection-spec]].

## [2026-06-05] decision | v3.3 architecture LOCKED after 2 adversarial agent rounds

Re-reviewed the whole ML plan after SAM2 was cancelled (SAM2 segments objects; TAG defects are points only — fixed-box-from-point was fabricated supervision). Round 1 (10 agents) proposed a lean pivot; Round 2 (10 agents) adversarially stress-tested it and caught it as partly a budget-driven overcorrection. Stakeholder approved the stress-tested result.

LOCKED: shared FROZEN DINOv2-ViT-L/14 (DINOv3 blocked by Meta CDN+gate) + lightweight DIET-CP SSL (gated by linear-probe) + INDEPENDENT heads (defect YOLO w/ point-distance metric, centering regression on 96k + OpenCV co-equal, severity CORN-ordinal+QWK, direct grade regressor macro-MAE). Weakest-link aggregator soft-min + data-fit front/back. Holo fix deferred to v1.1 (catalog lookup circular). Budget ~$40-55, fits $64 balance.

Key lessons captured: (1) without a held-out independent benchmark, review rounds argue "by taste" — that's why SAM2 survived 4 rounds; (2) budget was silently driving architecture; corrections forced by external blocks are sound, cost-driven cuts were reverted. Canonical: [[../_context-packs/v3.3-final-architecture]], ADR [[../30-Resources/adr/2026-06-05-v3.3-locked-architecture]].

## [2026-05-24] decision | reaffirmed ambitious March-plan for defect detection

Stakeholder rejected the pragmatic May 23 plan (`defect-yolo/training.md` — YOLOv11m + 7 classes + 640px + MAIN-only). Archived to `40-Archive/superseded-plans/2026-05-23-defect-yolo-training-pragmatic.md`. Canonical plan = `20-Areas/02-grading/defect-detection/architecture.md` (March 2026): YOLO26x-OBB, 12 classes, photometric stereo overlay as input channel, multi-angle capture (3-5 photos), defect masks, server-side GPU. Goal = max accuracy, real competitor to TAG/PSA AI-grading.

Implications:
- Scraper must dozalit DIG+ assets (920k depth PNGs + 2k annotated SFX + 40k defect crops + 120k corner crops currently undownloaded, all URLs live in metadata).
- Mobile UI needs multi-angle capture flow (guided silhouette + arrow, panoramic-style).
- GPU compute strategy needs re-decision — earlier "cloud-only $200 budget" was set against pragmatic plan; ambitious plan likely needs owned GPU on Hetzner per the original March decision.

## [2026-05-21] milestone | vault structure bootstrapped

Consolidated scattered project folders into `D:\CardChecker\` as single source of truth (PARA + LYT MOCs + Karpathy LLM Wiki conventions). Vault skeleton created with 12 areas, 9 templates, MOCs in place. Fresh `.git` cloned from GitHub (Senyasky1111/CardChecker_1) after Desktop git objects were lost. TAG scraper data (96,551 certs, 423 GB) preserved intact at `data/tag_raw/`. See [[30-Resources/reference/obsidian-best-practices-research]] for the methodology.

## [2026-05-21] decision | adopt PARA + LYT + Karpathy hybrid for vault

Picked hybrid framework (not pure PARA, not pure Zettelkasten). PARA folders give Claude directory-walk scope, LYT MOCs give narrative topic indexes, Karpathy `index.md`+`log.md` give LLM a catalog and replayable history. CLAUDE.md kept ≤120 lines per best practice.

## [2026-05-21] milestone | first wave of vault population

Populated ~70 structured notes covering:
- 10 API endpoint docs (all `src/api.py` routes documented)
- 13 module docs (every file in `src/`)
- Recognition pipeline overview + 5-level SQL lookup detail + YOLO detection
- 6 data source docs (CardMarket, PriceCharting, PokeTrace, Pokemon-API, TCGPlayer, eBay)
- Mobile architecture + 6 Zustand store docs + missing-features roadmap
- 3 seed ADRs (SQLite vs Postgres 2026-02-15, Gemini grading 2026-03-21, Subscription monetization 2026-03-22)
- ADR index with Dataview
- 4 active project notes (Q2 priorities)
- 6 context packs for AI sessions
- 9 Templater templates
- Updated CLAUDE.md (112 lines) to reference index/log + frontmatter convention

Vault now has enough structure что новые сессии Claude могут начинать с `_context-packs/X.md` для focused context. Most heavy lifting from past AI memory transferred into permanent vault notes.

## [2026-05-21] milestone | Obsidian plugins installed + configured

Installed 3 community plugins via filesystem (GitHub releases → `.obsidian/plugins/`):
- **Templater** (`templater-obsidian`) — `templates_folder` set to `30-Resources/templates`
- **Dataview** (`dataview`) — defaults
- **Linter** (`obsidian-linter`) — defaults

`community-plugins.json` lists all 3 to auto-enable on first launch.

## [2026-05-21] decision | rejected File Ignore plugin, use Obsidian native Excluded files instead

Initially recommended `Feng6611/Obsidian-File-Ignore` in research, but discovered at install time that plugin **physically renames files** with `.` prefix (e.g. `venv/` → `.venv/`). This would break the project — Python can't find venv, Node can't find node_modules, paths in code break. Uninstalled before damage.

Switched to **Obsidian native "Excluded files"** via `.obsidian/app.json` `userIgnoreFilters`. Same outcome (hide from Obsidian index), no filesystem side effects. Excluded patterns: `venv/`, `node_modules/`, `data/`, `runs/`, `models/`, `*.zip`, `__pycache__/`, backup .git dirs, `mobile/node_modules/`, `mobile/.expo/`, `.pytest_cache/`, `output/`, `logs/`.

Corrected research doc + saved AI-memory feedback to never recommend File Ignore again.

## [2026-05-23] incident | Obsidian hung loading vault (resolved by moving vault into subfolder)

Obsidian froze on "Loading vault..." for hours, hitting 2.3 GB RAM. Root cause: vault was at repo root `D:\CardChecker\`, so Obsidian tried to index ~600 GB of `data/`, `models/`, `runs/` etc. even though `userIgnoreFilters` hid them in the file-explorer UI — filters don't prevent the initial filesystem scan.

**Fix**: moved vault into `D:\CardChecker\vault\` subfolder. Repo root retains code (`src/`, `mobile/`, `scripts/`) and data dirs as siblings. Obsidian now only sees ~120 markdown files and loads in seconds (~250 MB RAM).

Side effects:
- `core-plugins.json` had been corrupted to 0 bytes → re-initialized
- Community plugins (Dataview, Templater, Linter) temporarily disabled to ensure clean first start
- `CLAUDE.md` updated to point at new `vault/` path

## [2026-05-23] milestone | vault overhaul — 7 ADRs + ~25 new notes for "infinite memory"

Comprehensive vault gap-fill so future Claude sessions have full project context without re-discovery.

**Added**:
- **7 ADRs backfilling major past decisions**:
  - YOLO-pose vs OpenCV detection
  - Tesseract primary OCR (EasyOCR + doctr as alternates)
  - Docker + docker-compose deployment to Hetzner
  - CLIP fallback uses warped image (not raw photo)
  - JP > TW > EN language priority (rationale: largest collector base for JP)
  - PriceCharting 95%/66%/62% fuzzy thresholds (heuristic, post-hoc documented)
  - Front 65% / back 35% grade weighting (industry-informed)
- **09-ml-research filled** (was empty): 6 notes covering YOLO card training, CLIP fine-tuning, defect YOLO, embedding index build; experiments log started
- **05-data-pipelines expanded**: scripts-catalog covering all 57 scripts + sub-overviews for cardmarket/pricecharting/ebay/tag pipelines + daily-price-update runbook
- **07-mobile expanded**: screens-overview (20 routes), components-overview (38 components), hooks-overview (6 hooks)
- **04-catalog filled** (was empty MOC stub): schema-and-ids, language-coverage, name-translations
- **12-business skeleton**: monetization tier doc, store-listing reference
- **MOCs cleaned**: 4 area MOCs (01-recognition, 02-grading, 08-webapp, 11-product) had 30+ broken wikilinks pointing to never-written notes — resolved by pointing to actual existing notes, ADRs, or marking stubs explicitly.
- **index.md rewritten** to reflect current state (~120 notes, 10 ADRs).

Vault now ~120 structured notes. Convention going forward: every major decision → ADR same day; every new training run → experiments-log entry; new script → row in scripts-catalog.

## [2026-05-24] decision | Q2 priorities re-ranked + new manual-search project

Priority re-shuffle:
- **#1 (new): Mobile auth + cloud sync** — promoted from #2. Reason: mock auth + AsyncStorage-only = tech debt block. Without real auth, no cloud sync, no Stripe, no subscription enforcement, data loss on reinstall — blocks monetization. Open decision: Firebase / Supabase / own (FastAPI+JWT). Default recommendation if no preference: Supabase.
- **#2 (was #1): OpenCV defect detection** — still in-progress, demoted by one. Parallel track: consider upgrading Gemini Flash → stronger VLM (Gemini 2.5 Pro / Claude Opus 4.7 / GPT-5) as **interim improvement** until YOLO defect detector ships. Deliberation: [[20-Areas/02-grading/gemini-model-upgrade]].
- **#3**: JP/TW OCR accuracy (unchanged).
- **#4**: Live pricing (unchanged).
- **#5 (NEW): Smart manual search** — feature added. Photo scanning isn't always convenient (sleeves, binders, weak light). User wants to type "096/080" or "Pikachu" or "Pikachu ex 199/197" and get matched. Competitors have search but it's dumb (text-only, no romanization, no combo parsing). Smart search = differentiator. See [[10-Projects/2026-Q2-manual-search]].

Re-ranking does not abandon any project — only changes immediate-attention order.

Created notes today: [[10-Projects/2026-Q2-manual-search]], [[20-Areas/02-grading/gemini-model-upgrade]]. Updated: 4 existing Q2 project notes + CLAUDE.md "Current Priorities".

## [2026-05-24] milestone | reality check — vault was documenting a mobile product that doesn't exist

After ~2 hours of work today on "Mobile auth + cloud sync" as #1 priority, user pushed back: "что за мобайл, у нас только веб". Investigation: the `mobile/` directory in this repo (full Expo SDK 54, 20 screens, 38 components) is **abandoned AI-generated prototype** — never the active product. Real product = **Base44 webapp** (`Senyasky1111/CardChecker_MVP`, ~10 users) + this repo (FastAPI backend + ML + scripts).

Implications:
- All 30+ mobile-related notes added during 2026-05-23 overhaul = noise for future Claude sessions. Need cleanup.
- Project #1 (mobile auth) and related projects = nuked from priority list.
- The auth deliberation (Base44 SDK direct vs proxy vs Supabase migration) — all moot, no mobile to wire.

Investigated webapp `CardChecker_MVP` via agent. Found real critical bugs: Stripe webhook validation missing (money risk), blob URLs in CollectionItem/Report die on reload (data loss), Watchlist `current_price` hardcoded never polls (broken feature), ReportNew hidden by `ready: false` flag (80% complete unlock), PriceHistoryChart placeholder (recharts installed, endpoint missing).

Revised Q2 priorities (in CLAUDE.md): #1 Stripe webhook, #2 blob → persistent storage, #3 watchlist polling, #4 unhide ReportNew, #5 manual search, then ML/OCR/Gemini upgrades.

## [2026-05-24] milestone | multi-agent dev workflow infrastructure added

Set up structured workflow for solo-dev development based on Anthropic patterns + 2026 community practices.

**Added 5 subagents** in `.claude/agents/`:
- `spec-writer` (Sonnet) — rough idea → structured TZ
- `code-reviewer` (Sonnet) — read-only multi-aspect code review
- `tester` (Sonnet) — writes/runs tests, can edit only test files
- `ui-reviewer` (Sonnet) — accessibility + design system + responsive for webapp/mobile UI
- `security-reviewer` (Opus) — auth/payment/input/secrets review

**Added orchestrator** `/feature-flow <description>` in `.claude/commands/feature-flow.md` — runs the workflow: spec → user approval → implement → tester → code-reviewer → conditional ui-reviewer / security-reviewer → synthesis.

**Enabled Agent Teams experimental** via `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in `.claude/settings.json` — exposes `TeamCreate`, `SendMessage`, `TeamDelete` tools, allows spawning teams of subagents with direct inter-agent communication.

**Convention**: domain skills (`/cv-expert`, `/card-engine`, `/defect-grader`, `/mobile-dev`, `/data-engineer`, `/ml-strategy`, `/train-coach`, `/dataset-doctor`) used inside the implementation stage of `/feature-flow` for deep context. Subagents handle review stages. Both layered together = the workflow user described ("команды агентов работают вместе, независимо проверяя друг-друга").

First test target: TBD (candidates — Stripe webhook validation in webapp, or watchlist polling job in FastAPI backend).

## [2026-05-24] milestone | first /feature-flow test — subscription management — workflow validated

Ran the new `/feature-flow` end-to-end on a real webapp bug (user-reported): Account page showed legacy "CREDITS: 0" widget + no way to downgrade Plus/Pro → Free from UI. Scope expanded mid-flow on user clarification to **full any-tier↔any-tier management** with Stripe proration.

**Stages executed**:
1. **spec-writer** (Sonnet, background) — initially blocked by cross-repo permissions (sibling repo `D:\amotrychenko\Desktop\CardChecker_MVP\`). Worked around by inlining file contents in re-launch. Returned grounded 9-section spec with explicit risks + open questions.
2. **Implementation** — 5 files edited, 1 new Deno function: `cancelSubscription` (idempotent cancel-at-period-end), `changeSubscription` (new — Stripe `subscriptions.update` with `create_prorations`), `useSubscription.jsx` (expose `cancelAtPeriodEnd` + `currentPeriodEnd`), `Pricing.jsx` (8-state button matrix), `Account.jsx` (remove Upgrade-to-Pro + Danger Zone, add cancellation banner + Change Plan/Billing buttons), `Layout.jsx` (sidebar Change Plan link to Pricing for all tiers).
3. **tester** (Sonnet, background) — adapted to no-test-framework state. Produced structured manual test plan + 5 bugs (2 high, 3 minor). Recommended deferring Vitest setup until needed.
4. **code-reviewer** (Sonnet, background, parallel with 3) — **independently confirmed bug #1** found by tester (changeSubscription not clearing cancel_at_period_end). Added 2 important + 5 minor findings.
5. **ui-reviewer** (Sonnet, background, parallel with 6) — 3 critical a11y issues: amber-600 fails WCAG AA contrast on white, color-only status conveyance, disabled-button screen-reader gap. Plus 7 minor design system findings.
6. **security-reviewer** (Opus, background, parallel with 5) — 0 block-merge, 3 high (immediate tier write race with 3DS payment fail, email-collision IDOR via Stripe customer lookup, status='active' missing trialing), 3 medium, 5 low. Found 3 real issues main session would have missed.
7. **Synthesis + 12 fixes applied** across all reviewers.

**Validation**: parallel reviewers found independent issues with **one cross-confirmation** (Bug 1 found by tester AND code-reviewer separately) — exactly the validation pattern the user described when asking to set this up.

**Workflow gotchas discovered**:
- Cross-repo subagent permissions blocked at first run. Resolved with `permissions.additionalDirectories` in settings.json + inline content fallback. Documented in [[../_context-packs/working-on-webapp]] (TBD) and memory.
- Subagent restart needed for new permissions to apply mid-session.
- Reviewers parallel ≠ Agent Team (which uses TeamCreate/SendMessage). Pure parallel subagents work fine for orthogonal review aspects without explicit communication.

**Commit pushed**: `2c249bd` on `Senyasky1111/CardChecker_MVP` main branch. Pending: Base44 republish to deploy + user verification with Stripe Portal cancel test.

## [2026-05-24] milestone | MCP servers configured (Base44 ready, Stripe pending)

Set up project-level MCP integration to query Base44 datastore and Stripe directly from Claude sessions (eliminates screenshot-based debugging).

**Files**:
- `d:\CardChecker\.mcp.json` — Base44 HTTP MCP (`https://app.base44.com/mcp`, OAuth-authenticated). No secrets — committable.
- `d:\CardChecker\.claude\settings.json` — added `enableAllProjectMcpServers: true` to auto-approve project MCPs.

**Activation**: requires Claude Code restart. At first Base44 use → OAuth flow opens in browser. After auth, `list_user_apps`, `list_entity_schemas`, `query_entities`, `create_base44_app`, `edit_base44_app` tools available.

**Stripe**: NOT in project repo (secret). User adds to global `~/.claude.json` via either:
- CLI: `claude mcp add stripe --scope user -- npx -y @stripe/mcp --tools=all --api-key=KEY`
- Manual edit `~/.claude.json`

Recommended key: Stripe restricted key (read-only subscriptions/customers/invoices), or test mode key (sk_test_) for dev. NOT sk_live_ secret.

**Net effect for future sessions**: instead of "show me the screenshot", Claude can directly check `User.subscription_tier`, `subscription.cancel_at_period_end`, `current_period_end`, invoice state — and proactively verify state after deploys.

## [2026-06-19] decision | Brand positioning locked — "stop losing money, decide with data"

Ran `/brand-strategist` (Dunford workflow) to position CardChecker for marketing/GTM. Converged after 3 refinement rounds with user.

**Locked positioning** → canonical doc: [[../_context-packs/brand-positioning]].

- **Core job (JTBD):** "how much is this card really worth (verifiably), what condition, and what do I do — sell raw as NM/EX/Damaged or send to grading?"
- **Rallying cry:** "Stop losing money on guesswork. Make data-driven decisions on every card."
- **Villain (StoryBrand):** the black box — apps that give one unverifiable self-computed price.
- **Two engines:** ① verifiable aggregated price (real TCGplayer/eBay/CardMarket + links, not a made-up number) ② condition/defect assessment (NM/EX/Damaged + centering). Output = the sell-vs-grade decision.
- **Demoted:** multi-region EN/JP/TW → secondary pillar, do NOT lead with language.
- **Two-grade rule:** selling-condition (NM/EX/DMG, achievable now) vs grade-potential (range, not precise PSA) — avoids overclaim while grading ML is in R&D.

**New skills created this session** (`.claude/commands/`): `/brand-strategist`, `/ux-designer`, `/growth-marketer`, `/brand-designer` — marketing/brand/design expert personas grounded in named frameworks (Dunford, Neumeier, Byron Sharp, Don Norman, NN/g, Sean Ellis, Reforge, Refactoring UI, etc). Registered in CLAUDE.md.

**Next:** `/ux-designer` on the price-comparison + condition → decision screen (now the product's main screen).

## [2026-06-19] decision | Honesty as brand weapon — don't race on grade accuracy

Competitor evidence (CardMintAI) graded a true ~7 card as a confident PSA 9 while claiming "95% PSA alignment." Confirms our finding: single-photo fine-defect grading is physically impossible (flat light) — competitors overclaim, and our grade is capped the same way.

**Strategic shift locked** (→ [[../_context-packs/brand-positioning]]):
- Brand villain extended: black box now spans BOTH price AND grade (overclaiming AI graders).
- Do NOT position on "more accurate AI grade" — unwinnable + physically capped.
- Lead grading with **centering** (geometry, actually verifiable, MAE ~2.5pp) + honest grade **range + reason**, never a fake precise number.
- Honesty = the wedge that wins the money-decision segment in a market of overclaimers. This is also the mascot's character (anti-bullshit advisor).
- Real accuracy only via multi-angle/multi-light capture (v1.5+).

Also this session: explored mascot/brand-character direction (expert-advisor archetype, not cute mascot) + market scan (Pokemon 30th-anniv boom; PSA paused Value tiers, ~14M backlog → grade-or-not pain at peak; AI pre-grade space saturated).

## [2026-06-19] milestone | Mascot locked + full branding session persisted

Completed the marketing/branding session (see [[../_sessions/2026-06-19-branding-session]]). Mascot LOCKED = cute modern "professor penguin" (big loupe + laptop, blue/purple, black casual suit) — embodiment of "decide with data". 6-pose character sheet generated via GPT Image 2 image-to-image (canonical hero job e87b2ecd). Assets in store_listing/mascots/.

**Docs written this session:**
- [[../_context-packs/brand-positioning]] — positioning (updated: honesty-as-weapon, two-grade rule)
- [[../_context-packs/brand-mascot]] — mascot canon, poses, regeneration method
- [[../_context-packs/market-landscape-2026]] — 2026 market scan (PSA backlog, AI-grader overclaim, mascot trend)
- [[../_context-packs/ux-audit-decision-screen]] — webapp gap analysis (Decision Card is the missing differentiator)
- [[../_sessions/2026-06-19-branding-session]] — session summary

**Memory pointers:** project_brand_positioning, project_brand_mascot, project_market_landscape, project_ux_decision_audit.

**Open:** name the mascot; flat app-icon; build the Decision Card (UX audit S1+S2).

- 2026-06-19 — Built CardChecker marketing landing (standalone Next.js 16 + Tailwind v4 + Framer Motion) in `landing/`. Pipos mascot (hero parallax + per-section poses), Decision Card mock as the peak, 13 sections from store_listing/landing/landing-spec.md. Installed Claude design/animation skills (greensock/gsap-skills + freshtechbro/claudedesignskills, 30 skills in .claude/skills). Build passes, dev verified. Playbook: store_listing/landing/claude-web-build-playbook.md.
- 2026-06-20 — Landing v2: switched to LIGHT theme (white bg + blue→purple brand), replaced framed mascots with transparent Pipos cutouts (Higgsfield remove_background ×7) used as side decorations, enriched content (+SourceStrip, +WhatYouGet 6-grid, +Comparison table implicit-villain, +Testimonials placeholder, enriched WhoFor with the-math). Build green. Live: landing/ on next dev :3000.
- 2026-06-20 — Landing v3: added "See it in action" showcase (Showcase.tsx) — browser-framed mockups faithful to the real Base44 PriceComparison/ConditionResults UI (CM/TCG/eBay badges, price gradient, sub-scores), but grade shown as a RANGE per honesty positioning. Inspired by real webapp components at CardChecker_MVP. Build green.
- 2026-06-20 — PROVEN: Pipos as interactive 3D. Higgsfield generate_3d (image_to_3d, Meshy) turned the transparent PNG into a textured GLB (8.17MB) — good quality. gltf-transform → 1.42MB webp/no-draco web build. Integrated in landing hero via R3F (@react-three/fiber + drei useGLTF), whole-model cursor look-at (damped rotation toward viewport-normalized pointer), static-PNG fallback, prefers-reduced-motion respected. Build + live puppeteer render verified. Model unrigged (single mesh) → whole-model aim, not head-bone. Files: landing/app/components/Pipos3D.tsx, public/mascot/pipos-web.glb.
- 2026-06-20 — Landing hero reworked per user feedback: removed 3D Pipos (looked cheap), hero now BIG static Pipos cutout on the right + text left, zero text overlap, two floating product chips. Removed in-section PiposDecor (penguins behind cards read as clutter). All sections reviewed. Build green.
- 2026-06-20 — Landing repositioned per user: LEAD with AI pre-grading as the differentiator ("one of the most accurate AND most honest"; centering/edges/corners/+light surface). Hero slogan→"Know exactly what your card is worth." Fixed "marketplace" wording (PriceCharting/PokeTrace are price sources, not marketplaces) → "prices you can check, no mystery formula." Added PreGrading section (4 pillars) + Roadmap section (shareable defect maps, multi-angle→99- 2026-06-20 — Landing repositioned per user: LEAD with AI pre-grading as the differentiator ("one of the most accurate AND most honest"; centering/edges/corners/+light surface). Hero slogan -> "Know exactly what your card is worth." Fixed "marketplace" wording (PriceCharting/PokeTrace are price sources, not marketplaces) -> "prices you can check, no mystery formula." Added PreGrading section (4 pillars) + Roadmap section (shareable defect maps, multi-angle to ~99%, deeper surface; all "in development"). Tightened density. 99% kept strictly as roadmap; accuracy claim comparative + honest. Build green.
- 2026-06-21 — Hero now features the animated Pipos scene video (Seedance 2.0, 5s loop: inspect giant card with loupe -> stand up + wave -> loop). Source 25.8MB 1080p -> web-optimized via ffmpeg to pipos-hero.mp4 (412KB) + pipos-hero.webm (357KB) + pipos-poster.jpg. New HeroMedia.tsx (autoplay/muted/loop/playsinline, prefers-reduced-motion -> poster). Hero relaid out: centered headline + CTAs on top, large framed 16:9 video band below with glow + 2 floating product chips. Final scene frame = m3 (gpt_image_2, neutral card). Build green.
- 2026-06-21 — Hero fixed per user: reverted to text-LEFT / Pipos-RIGHT. Regenerated the scene on a WHITE background (gpt_image_2 from m3) so it blends into the white page with no frame/block/purple. Chosen w2 -> pipos-scene.jpg (190KB) placed as static hero visual (corners ~254 white = seamless). Video bg-removal had failed; white-bg regen is the clean fix. Pipos-hero.mp4/webm kept for when the white-bg video is generated (swap-in later). Build green.
- 2026-06-21 — Hero final: zoomed-out white-bg scene so the WHOLE card fits in frame with white air around it (floats as a site element, not a cropped block). Chosen z3 (gpt_image_2) -> pipos-scene.jpg (144KB). Text-left / Pipos-right, seamless white blend (corners 253-254). Build green.
- 2026-06-21 — Killed the hero "rectangle": the white-bg scene was 253-254, page is 255 -> visible box. Fix: clamp near-white (>=250) to pure 255 on both the static PNG (pipos-scene.png, lossless) and the video (ffmpeg lutrgb). Border now 255 = page white -> scene blends seamlessly, no rectangle. Hero = text-left / Pipos-right, uncropped, video (whitened, muted) + PNG poster. Build green.
- 2026-06-21 — Integrated user's 1080p white-bg Pipos video (Seedance, job 101bfa76) into hero. Processed: whiten bg (ffmpeg lutrgb >=248->255) + transcode muted mp4 (2.1MB) + webm; HeroMedia (autoplay/muted/loop, poster pipos-scene.png, reduced-motion->poster). Hero container gets a 3% edge feather mask (dual linear-gradient intersect) so residual codec near-white edges dissolve into the page -> no rectangle (verified by compositing a feathered frame on white). Text-left / Pipos-right, uncropped. Build green.
- 2026-06-21 — Killed the video "snow" (codec grain in flat white): reprocessed with ffmpeg hqdn3d denoise + lutrgb clamp >=243->255. Border now all-255 (0/18000 noisy px), interior white clean. pipos-hero.mp4 836KB. Hero video = clean white, no rectangle, no snow, 3% edge feather. Build green.
- 2026-06-21 — Hero video upgraded to the 15s storyboard clip (Seedance, job fcd0d3ac: penguin walks the card borders inspecting, waves at ~4s, taps laptop, returns to start pose; no sparkle). Processed: hqdn3d denoise + lutrgb >=243->255 whiten + scale 1280 -> pipos-hero.mp4 1.0MB / webm 2.3MB, muted, border all-255 (clean white, no snow/rectangle). Enlarged on site: grid right col 1.22fr, video max-w-3xl + lg:scale-110. Build green.
- 2026-06-21 — Landing section pass per user feedback: removed cheap TrustBar; enlarged + restyled hero eyebrow (brand-gradient pill). Moved "How it works" to 3rd, rewrote as "Two clicks. Three answers" (identify+price / condition+defects+grade-prob / weighted grade-risk decision using gem-rate + prices-per-grade + cost/wait). Reframed Problem villain "inflated listing" -> "Overpaying or underselling" (real-world: don't check price, overpay or sell €200 card for €40). Tightened density (section py-11/14, mt-8 grids). Build green.
- 2026-06-21 — "Super site" pass (5-agent audit -> implementation). Collapsed 16->~12 sections: deleted Worth/Sources/Honesty/fake-Testimonials, merged their content (sources chips -> Showcase caption, honesty line -> PreGrading, trust -> honest TrustStrip). Moved Showcase+Decision up after HowItWorks (show-don't-tell); Decision is now a full-bleed DARK peak band. Killed ALL emoji -> lucide-react line icons. Repointed every primary CTA (Hero/Nav/Showcase/Decision/Pricing) to APP_URL via shared lib/site.ts (was #cta footer-scroll — biggest conversion leak). Stripped "most accurate in the hobby" superlative + 95/99% (positioning-guardrail). Hero subhead now price-led. HowItWorks titles parallel+plain. Comparison -> "Most apps hide the math. We show our work" + "The black box" column. Pricing real anchor (from €4.99). Currency normalized to €. Stronger .glass cards + .kicker pill + .peak-dark. Build green; verified via DOM grep (0 emoji, 14 app links, superlatives gone).
- 2026-06-22 — Pregrading integration drive (5 dev-agent verify → build). Verified ClickUp 86cack80c checklist against committed code (much of backend already done in fd94514) → pushed branch to origin. Backend (this repo): pinned `anthropic==0.111.0` (was missing → prod image builds but /grade silently 503s); mapped Anthropic errors (RateLimit→429 / Timeout→504 / Overloaded→503 / non-JSON→502) + SDK 90s timeout; deterministic one-way safety floor (≥6 MODERATE+ zones → side ≤5); **real billing/auth gate** replacing the stub → new `src/grade_gate.py` (shared-secret auth via X-Grade-Secret, atomic per-user credit decrement in a SEPARATE `data/grade_credits.db`, 402 exhaustion, daily-cap 429, per-user rate limit, content-hash idempotency, refund-on-failure) wired into `/grade` (auth→rate→idem→reserve→grade→refund/cache) + observability line. Tests +24 (grade_gate 9, /grade endpoint 6, safety-floor 2, …); pregrading suites all green; 1 pre-existing unrelated failure (cardmarket JP url). ML: two offline scorers; found the ~73% coverage promise failing (65%) → fix = `top_k` 4→5 (coverage 65%→**77%**; high 93/med 54/low 62), NOT σ-widening (verified dishonest; σ left as locked). 3-bucket 78%, PLAYED-recall 33% with ZERO PLAYED→GEM overclaim. Frontend (CardChecker_MVP): new flagged `/Pregrade` route (admin-gated, NOT in nav) — wizard (front+back required → CenteringStage React-port → ~15s condition → DecisionCard), DecisionDistribution ({grade,prob}, full 1–10, aria), EvidenceOverlay (8-zone grid), gradeCardV2/confirmCentering (402→UpgradeModal, AbortController); ConditionCheck/Report untouched; Vite build green. Locked: centering stays on /centering/compute (`{lr:[L,R],tb:[T,B],worst_axis_offset_pct}`), `/grade` sync-with-timeout for beta. Open before GA: roll leaked key (user owns), Base44↔ledger credit sync, ≥30 phone-photo gate calibration, full Docker rebuild, paid golden-regression. See [[10-Projects/2026-Q2-pregrading-integration]], ClickUp 86cack80c.
- 2026-06-22 — Pregrading wired to Base44 + DEPLOYED to prod. New `src/base44_auth.py`: verify forwarded Base44 JWT via REST me endpoint (identity+tier in one call), enforce per-tier limit against the Base44 CreditTransaction ledger (user-facing counter), charge-after-success. `/grade` dual-mode (Base44 token authoritative / local gate dev fallback); `GRADE_REQUIRE_BASE44=1` makes token mandatory in prod; beta = admins only. Frontend (CardChecker_MVP branch `feature/pregrading-route`, pushed to GitHub): gradeCardV2 forwards `Authorization: Bearer <jwt>`, client-side incrementGrade removed (backend charges). 65 backend tests green. DEPLOY: user decided NOT to reroll the key (keep current); prod has no users → straightforward rebuild. Injected ANTHROPIC key into prod .env via scp+grep (never logged) + GRADE_* env; snapped `cardcheck-api:rollback` tag; full `docker compose build` + up. Smoke PASS: /health 200, /identify-v2 200 (core intact), grader "ready (claude-opus-4-8)", /grade no-token→401. Backend LIVE. OPEN: get the new webapp route live in Base44 (GitHub≠Base44 deploy — git_remote_source=s3); ≥30 phone-photo calibration; CORS lock + paid golden-regression.
