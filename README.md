# CardChecker

Pokemon card scanner, grader & pricer. Point your phone at a card → app identifies it → grades its condition (PSA-style 1–10) → shows current market prices across CardMarket, PriceCharting, PokeTrace, and Pokemon API.

Supports **English, Japanese, and Traditional-Chinese cards** — ~50k cards in catalog.

> 🧠 Working with Claude Code on this repo? Start with [CLAUDE.md](CLAUDE.md). It's the project bootstrap context (skills, vault structure, conventions).

---

## What the app does

| Stage | How |
|---|---|
| **Detect** | OpenCV contour detection + YOLO-pose model. Outputs a 600×825 px perspective-corrected warp. |
| **Identify** | OCR (Tesseract / EasyOCR / doctr) → 5-level SQL lookup → CLIP/FAISS fallback. ~100 ms via `POST /identify-v2`. |
| **Grade** | Gemini 2.5 Flash on the warped front (+ optional back). Returns four pillar sub-grades (centering / corners / edges / surface) blended 65% front / 35% back. |
| **Price** | CardMarket (EN), PriceCharting (JP/TW/EN), PokeTrace, Pokemon API. Daily price snapshots in SQLite. |

Full architecture is one diagram in [CLAUDE.md](CLAUDE.md#architecture-one-liner). API endpoint reference: [vault/20-Areas/06-api/_MOC.md](vault/20-Areas/06-api/_MOC.md).

---

## Repository layout

```
src/                  Python backend (FastAPI, recognition, grading, pricing modules)
mobile/               React Native + Expo app (separate git history)
scripts/              Data pipeline scripts (scrapers, training entry points, ONNX export)
notebooks/            Jupyter notebooks for training & exploration
static/               Browser test harness (detect.html, index.html)
tests/                Unit + regression tests
data/                 SQLite DB + images (gitignored, ~580 GB on full clone)
models/               Trained weights & FAISS indexes (gitignored)
vault/                Obsidian knowledge base (PARA structure, see below)
store_listing/        App/Play Store assets + descriptions
.claude/              Claude Code skills and subagents
```

### Vault — where decisions and context live

The repo doubles as an Obsidian vault under `vault/`. We use [PARA](https://fortelabs.com/blog/para/):

- [vault/10-Projects/](vault/10-Projects/) — active Q-level sprints
- [vault/20-Areas/](vault/20-Areas/) — 12 long-lived domains (recognition, grading, pricing, catalog, data-pipelines, api, mobile, webapp, ml-research, infrastructure, product, business) — each has a `_MOC.md` (Map of Content)
- [vault/30-Resources/](vault/30-Resources/) — ADRs, templates, references, web clippings
- [vault/40-Archive/](vault/40-Archive/) — done projects, deprecated decisions
- [vault/_context-packs/](vault/_context-packs/) — curated note bundles for AI sessions
- [vault/index.md](vault/index.md) — vault TOC · [vault/log.md](vault/log.md) — append-only journal

---

## Quick start

### Backend (Python 3.11.9)

```bash
# Windows
./venv/Scripts/python.exe -m uvicorn src.api:app --host 0.0.0.0 --port 8000
# Linux/Mac
./venv/bin/python -m uvicorn src.api:app --host 0.0.0.0 --port 8000
```

API is now on http://localhost:8000 . Browser test harness: http://localhost:8000/static/index.html

### Mobile (React Native + Expo SDK 54)

```bash
cd mobile && npx expo start
```

### Production

Hetzner 89.167.31.124 · Docker at `/opt/cardcheck/` · safety rules in [vault/20-Areas/10-infrastructure/deploy-safety-rules.md](vault/20-Areas/10-infrastructure/deploy-safety-rules.md).

---

## ML / Computer Vision work

CardChecker has a defect-detection track separate from Gemini grading: a pipeline that learns from TAG Grading's ~96k DIG reports to flag corner wear, edge wear, surface damage, scratches, creases, dents and stains on the card without needing an LLM at inference.

| Asset | Size | Purpose |
|---|---|---|
| `data/tag_raw/` | 423 GB | 96 547 TAG cert dumps (metadata + raw scans + DIG+ overlays) |
| `data/tag_dataset_1280/` | 11 GB | 23 116 images / 57 614 YOLO boxes (7 classes), 1280 px |
| `data/cards.db` | 369 MB | 50k+ card catalog (EN/JP/TW), price snapshots |

### Training infrastructure

**Cloud-first.** Local dev box has only an RTX 4060 mobile (8 GB VRAM) — fine for sanity-runs on a tiny subset, not for real training. Real runs go on RunPod / Vast.ai / Lambda (RTX 4090 spot ~$0.40/hr, H100 ~$2.50/hr).

### Iteration loop (Claude Code skills)

When working on the ML side, use these slash-commands in Claude Code:

| Skill | What it does |
|---|---|
| [`/cv-expert`](.claude/commands/cv-expert.md) | SOTA CV/DL research (foundation models, ONNX, benchmarks) |
| [`/dataset-doctor`](.claude/commands/dataset-doctor.md) | Diagnose imbalance, leakage, label noise in a dataset |
| [`/ml-strategy`](.claude/commands/ml-strategy.md) | Pick model / backbone / split strategy for a task |
| [`/train-coach`](.claude/commands/train-coach.md) | Build training configs (loss, augs, schedule) for cloud GPU |
| [`/review-run`](.claude/commands/review-run.md) | Audit a finished `runs/expN/` (spawns the `model-reviewer` subagent) |
| [`/card-engine`](.claude/commands/card-engine.md) | Recognition pipeline context (OCR, SQL, CLIP, CardMarket) |
| [`/defect-grader`](.claude/commands/defect-grader.md) | Gemini grading + defect detection roadmap |
| [`/data-engineer`](.claude/commands/data-engineer.md) | Dataset / scraping pipelines |
| [`/mobile-dev`](.claude/commands/mobile-dev.md) | Mobile app (RN + Expo + Zustand stores) |

---

## API endpoints (selected)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/identify-v2` | OCR+SQL identification (~100 ms) — **preferred** |
| POST | `/identify` | Legacy CLIP identification (~1 s) |
| POST | `/detect-card` | Card detection + perspective correction |
| POST | `/detect-number` | OCR number extraction only |
| GET | `/card/{id}` | Card details + pricing |
| GET | `/card/{tcgdex_id}/prices` | Multi-source pricing |
| POST | `/gemini/identify` | Gemini Vision identification |
| POST | `/gemini/grade` | AI condition grading (front + optional back) |

Full reference: [vault/20-Areas/06-api/_MOC.md](vault/20-Areas/06-api/_MOC.md).

---

## Contributing / working in this repo

1. Read [CLAUDE.md](CLAUDE.md) for the working conventions.
2. Significant change? → write an ADR in [vault/30-Resources/adr/](vault/30-Resources/adr/) using `templates/adr.md`.
3. Decision/incident? → append one line to [vault/log.md](vault/log.md).
4. Never deploy untested code (see [deploy-safety-rules](vault/20-Areas/10-infrastructure/deploy-safety-rules.md)).

---

## License

Private project. All rights reserved.
