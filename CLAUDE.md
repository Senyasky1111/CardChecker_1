# CardChecker — Pokemon Card Scanner, Grader & Pricer

## What This Does

Scan a Pokemon card → identify it → grade condition → get market prices.
Supports EN/JP/TW cards (~50K total in catalog).

User-facing intro lives in [README.md](README.md). This file is the bootstrap context for Claude Code.

## Read These FIRST

- [vault/index.md](vault/index.md) — catalog of MOCs / ADRs / active projects
- [vault/log.md](vault/log.md) — append-only chronological journal
- [README.md](README.md) — human-facing overview

## Architecture (one-liner)

```
Mobile (RN+Expo) ─┐
Webapp (Base44) ──┼─→ FastAPI (src/api.py) → [Identify → Grade → Pricing]
                  ┘            ↓
        Detection (OpenCV/YOLO) → OCR (Tesseract/EasyOCR/doctr) → 5-level SQL match → CLIP fallback
        Grading: Gemini 2.5 Flash, 4 pillars (centering/corners/edges/surface), front 65%/back 35%
        Pricing: CardMarket (EN), PriceCharting (95%/66%/62%), PokeTrace, Pokemon API
```

## Vault structure (lives in `vault/`)

- [vault/10-Projects/](vault/10-Projects/) — active sprints (Q-level)
- [vault/20-Areas/](vault/20-Areas/) — 12 long-lived domains. Each has `_MOC.md`:
  recognition, grading, pricing, catalog, data-pipelines, api, mobile, webapp,
  ml-research, infrastructure, product, business.
- [vault/30-Resources/](vault/30-Resources/) — `adr/`, `templates/`, `reference/`, `clippings/`
- [vault/40-Archive/](vault/40-Archive/) — done projects, deprecated decisions
- [vault/_context-packs/](vault/_context-packs/) — curated note bundles for AI sessions
- [vault/_daily/](vault/_daily/), [vault/_weekly/](vault/_weekly/) — periodic notes

## Conventions for the vault

- **Frontmatter required on every note**: `type`, `status`, `area`, `tags`, `created`, `updated`. Use templates in `vault/30-Resources/templates/`.
- **One thing per note** — one API endpoint, one module, one ADR, one competitor. Not "everything about CLIP".
- **TL;DR in first line below title** — RAG grabs top of file first.
- **Heading hygiene** — one concept per H2, max H3 depth.
- **Linking**: `[[wikilink]]` for vault-internal, `[text](relative/path)` for code (e.g. [src/card_matcher.py](src/card_matcher.py)).
- **Non-obvious decisions** → write ADR in `vault/30-Resources/adr/` using `templates/adr.md`, date-as-ID (`YYYY-MM-DD-slug.md`).
- **Significant changes** → append one line to [vault/log.md](vault/log.md).
- **Don't document what code already shows** — only the non-obvious: decisions, tradeoffs, history.
- **Don't crawl** `data/`, `venv/`, `node_modules/`, `models/`, `runs/`, `*.zip`.

## Skills (use `/command` for deep context)

Domain skills already in [.claude/commands/](.claude/commands/):
- `/cv-expert` — Senior CV/DL research engineer. SOTA (2024-2026), benchmarking, ONNX, training.
- `/card-engine` — Detection + OCR + SQL matching + CLIP fallback + CardMarket pricing.
- `/defect-grader` — Gemini grading, 4 pillars, PSA-style 1-10, defect detection roadmap.
- `/mobile-dev` — RN 0.81.5 + Expo 54, 6 Zustand stores, i18n (en/de/fr).
- `/data-engineer` — Dataset pipelines, scraping architecture.

ML-iteration skills (defect-detection training loop):
- `/ml-strategy` — Picks model/backbone/split strategy from current data state.
- `/dataset-doctor` — Diagnoses dataset health (imbalance, leakage, label noise, era/lang stratification).
- `/train-coach` — Builds training configs (loss, augmentations, schedule) for a given task.
- `/review-run <runs/expN>` — Manual entry point to spawn the `model-reviewer` subagent.

Subagent in [.claude/agents/](.claude/agents/):
- **model-reviewer** — read-only post-training auditor. Reads `runs/expN/results.csv`, confusion matrix, per-class AP, picks 20 worst val examples and gives 3-5 actionable changes for next run.

Hook in [.claude/settings.json](.claude/settings.json):
- After any `Bash` invocation matching `train_yolo|train_defect_yolo|yolo train`, prints a hint to invoke the model-reviewer on the freshest `runs/` folder. Auto-discoverable, not auto-spawning.

## Code structure (parallel to vault)

```
src/                        # Python backend
  api.py                    # FastAPI (20 endpoints)
  card_matcher.py           # OCR+SQL+CLIP pipeline
  card_detector.py          # OpenCV detection
  yolo_card_detector.py     # YOLO-pose detection
  doctr_detector.py         # doctr OCR
  ocr.py                    # Tesseract/EasyOCR
  recognizer.py             # CLIP recognizer (legacy)
  cardmarket_url.py         # Marketplace URLs
  ebay_url.py               # eBay URLs
  gemini_grade.py           # Gemini grading
  gemini_identify.py        # Gemini ID
  text_index.py             # Text search
  db.py                     # SQLite schema/queries
  config.py                 # Env config
mobile/                     # React Native + Expo
scripts/                    # Data pipeline scripts (scrape_tag.py, train_defect_yolo.py, ...)
notebooks/                  # Jupyter training/exploration notebooks
data/                       # SQLite + images (gitignored, ~580 GB)
models/                     # CLIP index, YOLO weights (gitignored)
.claude/commands/           # Slash-command skills
.claude/agents/             # Subagent definitions
vault/                      # Obsidian knowledge base (PARA structure)
```

## Quick Start

```bash
# Backend
./venv/Scripts/python.exe -m uvicorn src.api:app --host 0.0.0.0 --port 8000

# Mobile
cd mobile && npx expo start
```

## API Endpoints (canonical reference: [vault/20-Areas/06-api/_MOC.md](vault/20-Areas/06-api/_MOC.md))

| Method | Path | Description |
|--------|------|-------------|
| POST | `/identify-v2` | OCR+SQL identification (~100ms) — **preferred** |
| POST | `/identify` | Legacy CLIP identification (~1s) |
| POST | `/detect-card` | Card detection + perspective correction |
| POST | `/detect-number` | OCR number extraction only |
| GET | `/card/{id}` | Card details + pricing |
| GET | `/card/{tcgdex_id}/prices` | Multi-source pricing |
| POST | `/gemini/identify` | Gemini Vision identification |
| POST | `/gemini/grade` | AI condition grading (front + optional back) |

## Deployment

- **Production**: Hetzner 89.167.31.124, Docker at `/opt/cardcheck/`. See [vault/20-Areas/10-infrastructure/_MOC.md](vault/20-Areas/10-infrastructure/_MOC.md).
- **Local Python**: always use `./venv/Scripts/python.exe` (Python 3.11.9, all deps).
- **Database**: SQLite WAL at `data/cards.db` (369 MB).
- ⚠️ **Deploy safety**: NEVER deploy untested code, NEVER deploy beyond intended files. See [vault/20-Areas/10-infrastructure/deploy-safety-rules.md](vault/20-Areas/10-infrastructure/deploy-safety-rules.md).

## Training compute

Cloud-first (RunPod / Vast.ai / Lambda). Local laptop has RTX 4060 mobile (8 GB) — use for sanity-runs only (≤2 epochs on a 500-img subset). Full training and DINOv2 SSL pretrain go on rented H100/A100/RTX 4090. Budget envelope: ~$50 per full YOLOv8m run, ~$30-60 per DINOv2 pretrain.

## Current Priorities

1. **Defect detection ML pipeline** — train on TAG dataset (~23k labelled, ~33k unlabelled scans). See [vault/10-Projects/2026-Q2-opencv-defects.md](vault/10-Projects/2026-Q2-opencv-defects.md).
2. Mobile: real auth + cloud sync → [vault/10-Projects/2026-Q2-mobile-auth-and-cloud.md](vault/10-Projects/2026-Q2-mobile-auth-and-cloud.md)
3. Recognition: improve JP/TW OCR accuracy → [vault/10-Projects/2026-Q2-jp-tw-ocr-accuracy.md](vault/10-Projects/2026-Q2-jp-tw-ocr-accuracy.md)
4. Pricing: live price updates instead of daily snapshots → [vault/10-Projects/2026-Q2-live-pricing.md](vault/10-Projects/2026-Q2-live-pricing.md)
