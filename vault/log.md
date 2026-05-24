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
