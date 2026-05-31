# CardChecker — Pokemon Card Scanner, Grader & Pricer

## What This Does

Scan a Pokemon card → identify it → grade condition → get market prices.
Supports EN/JP/TW cards (~50K total in catalog).

User-facing intro lives in [README.md](README.md). This file is the bootstrap context for Claude Code.

## Read These FIRST

- [vault/index.md](vault/index.md) — catalog of MOCs / ADRs / active projects
- [vault/log.md](vault/log.md) — append-only chronological journal
- [README.md](README.md) — human-facing overview

## Working principles (Karpathy-derived, 2026-05-30)

For non-trivial work — anything you'd run through `/feature-flow`:

- **Surface assumptions before coding.** If the request has >1 reasonable interpretation, list them and ask — don't pick silently and discover later that you built the wrong thing.
- **Push back when you see a simpler path.** If the user asks for a 200-line refactor and 30 lines would do, say so before implementing the 200.
- **Stop when confused.** Name what's unclear, ask one focused question. Don't paper over with plausible-looking code.
- **Goal-driven for bugfixes.** Reproduce the bug as a failing test FIRST, then fix until green. Strong success criteria beat clarification loops.

Skip this rigor for trivial work (typos, one-liners, doc tweaks) — judgment call.

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
- [vault/_sessions/](vault/_sessions/) — **per-session summaries**. Read latest entry first when starting new session to know what was done last. Raw transcripts live at `~/.claude/projects/d--CardChecker/*.jsonl` (Claude Code's own storage).
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

Utility skills:
- `/brief` — Plain-language recap of current context (≤3 paragraphs, no jargon).

Multi-agent dev workflow (added 2026-05-24):
- `/feature-flow <description>` — Orchestrated workflow: spec-writer → user approval → implementation → tester → code-reviewer → ui-reviewer (if frontend) → security-reviewer (if security-relevant). Use for any non-trivial change.

Subagents in [.claude/agents/](.claude/agents/):
- **model-reviewer** — read-only post-training auditor (ML runs).
- **spec-writer** — turns rough idea into structured TZ before implementation.
- **code-reviewer** — read-only multi-aspect review of changed files. Sonnet.
- **tester** — writes/runs tests, reports failures. Can edit test files only.
- **ui-reviewer** — read-only UI/UX/accessibility review for webapp + mobile. Sonnet.
- **security-reviewer** — read-only security review for auth/payment/input/secrets changes. Opus.

Hook in [.claude/settings.json](.claude/settings.json):
- After any `Bash` invocation matching `train_yolo|train_defect_yolo|yolo train`, prints a hint to invoke the model-reviewer on the freshest `runs/` folder. Auto-discoverable, not auto-spawning.

Agent Teams (experimental) enabled via `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in [.claude/settings.json](.claude/settings.json) — allows spawning teams of subagents that communicate directly (mailbox + shared task list). Use sparingly: each teammate = full Claude instance = full context cost.

## MCP servers

- **Base44 MCP** — configured in [.mcp.json](.mcp.json), auto-approved via `enableAllProjectMcpServers`. OAuth-authenticated at first use. Tools: `list_user_apps`, `list_entity_schemas`, `query_entities`, `create_base44_app`, `edit_base44_app`. Use for querying CardChecker Plus user state, entity records, verifying deploys.
- **Stripe MCP** — NOT in project repo (secret). User adds to `~/.claude.json` via `claude mcp add stripe --scope user -- npx -y @stripe/mcp --tools=all --api-key=KEY`. Use restricted key from Stripe Dashboard, not `sk_live_`. After connection: query subscription state, customer records, invoices, proration directly instead of asking for screenshots.

## Cross-repo work (webapp at sibling path)

Real product webapp is at `D:\amotrychenko\Desktop\CardChecker_MVP\` (separate repo, ~10 users). When working on webapp from this session, `permissions.additionalDirectories` in `.claude/settings.json` already includes that path. **But subagents may need session restart to pick up the broader scope** — if you get permission errors mid-session, either restart or inline file contents in subagent prompts as fallback. NOTE: `mobile/` directory in THIS repo is abandoned AI-generated prototype, not part of active product. Skip it for planning.

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

## Current Priorities (re-ranked 2026-05-24)

1. **Mobile auth + cloud sync** — promoted from #2; tech debt block (mock auth, no sync, data loss on reinstall). See [vault/10-Projects/2026-Q2-mobile-auth-and-cloud.md](vault/10-Projects/2026-Q2-mobile-auth-and-cloud.md). Open decision: Firebase / Supabase / own.
2. **Defect detection ML pipeline** — train on TAG dataset (~23k labelled, ~33k unlabelled scans). See [vault/10-Projects/2026-Q2-opencv-defects.md](vault/10-Projects/2026-Q2-opencv-defects.md). Parallel: consider Gemini model upgrade as interim — [vault/20-Areas/02-grading/gemini-model-upgrade.md](vault/20-Areas/02-grading/gemini-model-upgrade.md).
3. **Recognition: JP/TW OCR accuracy** → [vault/10-Projects/2026-Q2-jp-tw-ocr-accuracy.md](vault/10-Projects/2026-Q2-jp-tw-ocr-accuracy.md)
4. **Pricing: live price updates** → [vault/10-Projects/2026-Q2-live-pricing.md](vault/10-Projects/2026-Q2-live-pricing.md)
5. **🆕 Smart manual search** (number / name / combo, smart catalog lookup) → [vault/10-Projects/2026-Q2-manual-search.md](vault/10-Projects/2026-Q2-manual-search.md)
