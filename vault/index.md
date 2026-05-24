---
type: index
status: active
updated: 2026-05-23
---

# CardChecker Vault Index

> **Read this first.** Курированный catalog ключевых нот для AI-сессий и human navigation.
> Also see [[log]] для chronological event journal, `/CLAUDE.md` (repo root) для AI conventions.

---

## 🔁 Pipeline overview

```
Photo → Detection (YOLO-pose) → Warp → OCR (Tesseract/EasyOCR/doctr)
                                        ↓
                                   5-level SQL match → CLIP/FAISS fallback
                                        ↓
                                   Identified card
                                        ↓
                                   Gemini grading (4 pillars, 65/35 weights)
                                        ↓
                                   Multi-source pricing
                                   (CardMarket / TCGPlayer / PriceCharting / eBay / PokeTrace)
```

См. [[20-Areas/01-recognition/pipeline-overview]] для деталей.

---

## 🗂️ Areas (12)

### 01-recognition (опознавание карты)
- [[20-Areas/01-recognition/_MOC]] ⭐
- [[20-Areas/01-recognition/pipeline-overview]] — end-to-end
- [[20-Areas/01-recognition/detection/yolo-pose]] — primary detector
- [[20-Areas/01-recognition/matching/5-level-sql-lookup]] ⭐ — core algorithm

### 02-grading (оценка состояния)
- [[20-Areas/02-grading/_MOC]] ⭐
- [[20-Areas/02-grading/defect-detection/architecture]] — defect detection roadmap

### 03-pricing (цены)
- [[20-Areas/03-pricing/_MOC]]
- Sources:
  - [[20-Areas/03-pricing/sources/cardmarket]] ⭐ — primary EU
  - [[20-Areas/03-pricing/sources/pricecharting]] — EN 95% / JP 66% / TW 62%
  - [[20-Areas/03-pricing/sources/poketrace]] — graded prices (PSA/CGC/BGS)
  - [[20-Areas/03-pricing/sources/pokemon-api-rapidapi]] — TCGPlayer USD via proxy
  - [[20-Areas/03-pricing/sources/tcgplayer]] — US market
  - [[20-Areas/03-pricing/sources/ebay]] — sold listings

### 04-catalog (метаданные карт) ⭐ NEW
- [[20-Areas/04-catalog/_MOC]]
- [[20-Areas/04-catalog/schema-and-ids]] — DB schema + ID systems
- [[20-Areas/04-catalog/language-coverage]] — EN/JP/TW breakdown
- [[20-Areas/04-catalog/name-translations]] — Gemini-assisted EN names

### 05-data-pipelines (57 scripts)
- [[20-Areas/05-data-pipelines/_MOC]]
- [[20-Areas/05-data-pipelines/scripts-catalog]] ⭐ — **inventory всех 57 scripts**
- [[20-Areas/05-data-pipelines/cardmarket/overview]]
- [[20-Areas/05-data-pipelines/pricecharting/overview]]
- [[20-Areas/05-data-pipelines/ebay-scraping/overview]]
- [[20-Areas/05-data-pipelines/tag-scraping/overview]] ⭐ — 96K cards, 423 GB
- [[20-Areas/05-data-pipelines/runbooks/daily-price-update]] — scheduled task

### 06-api (FastAPI backend)
- [[20-Areas/06-api/_MOC]]
- **Endpoints**:
  - [[20-Areas/06-api/endpoints/identify-v2]] ⭐ — preferred (~100ms)
  - [[20-Areas/06-api/endpoints/identify]] — legacy CLIP
  - [[20-Areas/06-api/endpoints/detect-card]]
  - [[20-Areas/06-api/endpoints/detect-number]]
  - [[20-Areas/06-api/endpoints/card-by-id-product]]
  - [[20-Areas/06-api/endpoints/card-by-tcgdex-id-prices]] ⭐ — multi-source pricing
  - [[20-Areas/06-api/endpoints/card-by-tcgdex-id-price-history]]
  - [[20-Areas/06-api/endpoints/gemini-identify]]
  - [[20-Areas/06-api/endpoints/gemini-grade]] ⭐
  - [[20-Areas/06-api/endpoints/health]]
- **Modules**:
  - [[20-Areas/06-api/modules/card_matcher]] ⭐ — heart of `/identify-v2`
  - [[20-Areas/06-api/modules/card_detector]], [[20-Areas/06-api/modules/yolo_card_detector]], [[20-Areas/06-api/modules/doctr_detector]]
  - [[20-Areas/06-api/modules/ocr]] (1118 lines, largest)
  - [[20-Areas/06-api/modules/recognizer]] — CLIP
  - [[20-Areas/06-api/modules/cardmarket_url]], [[20-Areas/06-api/modules/ebay_url]]
  - [[20-Areas/06-api/modules/gemini_grade]], [[20-Areas/06-api/modules/gemini_identify]]
  - [[20-Areas/06-api/modules/text_index]]
  - [[20-Areas/06-api/modules/db]] — SQLite schema
  - [[20-Areas/06-api/modules/config]]

### 07-mobile (RN + Expo)
- [[20-Areas/07-mobile/_MOC]]
- [[20-Areas/07-mobile/architecture]] ⭐ — stack, structure
- [[20-Areas/07-mobile/api-client]] — HTTP layer
- [[20-Areas/07-mobile/screens-overview]] ⭐ NEW — 20 routes
- [[20-Areas/07-mobile/components-overview]] ⭐ NEW — 38 components
- [[20-Areas/07-mobile/hooks-overview]] NEW — 6 hooks
- [[20-Areas/07-mobile/missing-features]] — production blockers
- Stores (Zustand): collection, scan, grading, watchlist, settings, auth, market

### 08-webapp (Base44)
- [[20-Areas/08-webapp/_MOC]] — pointer to separate repo

### 09-ml-research ⭐ FILLED
- [[20-Areas/09-ml-research/_MOC]]
- YOLO card detection: [[20-Areas/09-ml-research/yolo-card-detection/training]], [[20-Areas/09-ml-research/yolo-card-detection/dataset]]
- CLIP fine-tuning: [[20-Areas/09-ml-research/clip-finetuning/strategy]], [[20-Areas/09-ml-research/clip-finetuning/pairs-generation]]
- Defect YOLO: [[20-Areas/09-ml-research/defect-yolo/training]]
- Embedding index: [[20-Areas/09-ml-research/embedding-index/build-process]]
- [[20-Areas/09-ml-research/experiments-log]] — append-only

### 10-infrastructure (deploy, runbooks)
- [[20-Areas/10-infrastructure/_MOC]]
- [[20-Areas/10-infrastructure/hetzner-server]]
- [[20-Areas/10-infrastructure/deploy-procedure]]
- [[20-Areas/10-infrastructure/deploy-safety-rules]] ⚠️

### 11-product (vision, strategy)
- [[20-Areas/11-product/_MOC]] — skeleton

### 12-business (marketing, legal, finance)
- [[20-Areas/12-business/_MOC]] — skeleton
- [[20-Areas/12-business/monetization]] — subscription tiers
- [[20-Areas/12-business/store-listing]] — App Store copy

---

## 🎯 Active projects (Q2 2026)

```dataview
TABLE priority AS "P", status, area FROM "10-Projects"
WHERE type = "project"
SORT priority ASC
```

- **#1** [[10-Projects/2026-Q2-opencv-defects]] — defect detection layer
- **#2** [[10-Projects/2026-Q2-mobile-auth-and-cloud]] — real auth + cloud sync
- **#3** [[10-Projects/2026-Q2-jp-tw-ocr-accuracy]] — improve JP/TW OCR
- **#4** [[10-Projects/2026-Q2-live-pricing]] — live prices vs daily snapshots

---

## 🧭 ADRs (10)

Source of truth: [[30-Resources/adr/]].

**Existing (3, from initial vault bootstrap)**:
- [[30-Resources/adr/2026-02-15-sqlite-not-postgres]]
- [[30-Resources/adr/2026-03-21-gemini-for-grading-not-custom-model]]
- [[30-Resources/adr/2026-03-22-monetization-subscription-not-credits]]

**Backfilled 2026-05-23 (7)**:
- [[30-Resources/adr/2026-05-23-yolo-pose-not-opencv-detection]]
- [[30-Resources/adr/2026-05-23-tesseract-primary-easyocr-doctr-fallback]]
- [[30-Resources/adr/2026-05-23-docker-compose-deployment]]
- [[30-Resources/adr/2026-05-23-clip-fallback-uses-warped-image]]
- [[30-Resources/adr/2026-05-23-jp-over-tw-language-priority]]
- [[30-Resources/adr/2026-05-23-pricecharting-fuzzy-match-thresholds]]
- [[30-Resources/adr/2026-05-23-grade-weights-front-65-back-35]]

```dataview
TABLE date, status FROM "30-Resources/adr"
WHERE type = "adr"
SORT date DESC
```

---

## 📦 Context packs (для AI-сессий)

Начинай сессию с **"Claude, прочитай `_context-packs/X.md`"**:

- [[_context-packs/working-on-defect-detection]]
- [[_context-packs/working-on-recognition]]
- [[_context-packs/working-on-pricing]]
- [[_context-packs/debugging-tag-scraper]]
- [[_context-packs/deploying-to-prod]] ⚠️
- [[_context-packs/monetization-decisions]]

---

## 📚 Reference

- [[30-Resources/reference/obsidian-best-practices-research]] — методология vault'a
- `30-Resources/templates/` — 9 шаблонов

---

## ⚙️ Vault location

Vault — это **`vault/` subfolder** of repo `D:\CardChecker\`. Repo root содержит код (`src/`, `mobile/`, `scripts/`, etc.) и data dirs (`data/`, `models/`, `venv/`).

Vault not at repo root, чтобы Obsidian не пытался индексировать 600+ GB `data/`. См. [[log#2026-05-23]] для истории.

---

## 🔢 Stats (2026-05-23 snapshot)

- **~120 notes total**, organized по PARA + LYT
- **12 areas** с _MOC.md
- **10 ADRs** (3 original + 7 backfilled today)
- **10 API endpoints** + **13 modules** documented (each src/ file covered)
- **57 scripts** in catalog + 4 sub-area overviews + 1 runbook
- **20 mobile routes**, **38 components**, **6 hooks**, **6 stores** documented
- **6 context packs** for AI sessions
- **4 active Q2 projects**
- **9 templates** в `30-Resources/templates/`
