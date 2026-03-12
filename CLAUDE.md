# CardChecker — Pokemon Card Scanner, Grader & Pricer

## What This Does

Scan a Pokemon card → identify it → grade condition → get market prices. Supports EN/JP/TW cards (50K+ total).

## Architecture Overview

```
                    ┌─────────────┐
                    │  Mobile App │  (React Native / Expo)
                    └──────┬──────┘
                           │ REST API
                    ┌──────▼──────┐
                    │   FastAPI   │  src/api.py
                    └──────┬──────┘
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ Identify │ │  Grade   │ │  Pricing │
        └────┬─────┘ └────┬─────┘ └────┬─────┘
             │            │            │
   Detection → OCR    Gemini Vision   CardMarket
   → SQL Match         4 pillars     + PokeTrace
   → CLIP fallback    PSA-style 1-10  + Pokemon API
```

## Three Domains (use `/command` skills for deep context)

### `/card-engine` — Recognition & Pricing
- **Detection**: OpenCV contours + YOLO-pose, outputs 600x825 warped image
- **Identification**: OCR → 5-level SQL lookup → CLIP/FAISS fallback
- **Pricing**: CardMarket (idProduct redirect for EN, search URL for JP/TW)
- **Database**: SQLite, 22K EN + 15K JP + 12K TW cards, daily price snapshots
- **API**: 7 endpoints, `/identify-v2` preferred (~100ms)

### `/defect-grader` — Condition Analysis
- **Grading**: Gemini 2.5 Flash, PSA-style 1-10 scale
- **4 Pillars**: Centering, Corners, Edges, Surface (front 65% + back 35%)
- **Defects**: type + location + severity + visibility per defect
- **Roadmap**: OpenCV defect detection, calibration dataset, multi-model ensemble

### `/mobile-dev` — Mobile App
- **Stack**: React Native 0.81.5, Expo SDK 54, TypeScript strict
- **State**: 6 Zustand stores with AsyncStorage persistence
- **Features**: scan, collection, grading, market/watchlist, i18n (en/de/fr)
- **Missing**: real auth, live price polling, push notifications, cloud sync

## Project Structure

```
CardRecognition/
├── src/                        # Backend Python
│   ├── api.py                  # FastAPI server (all endpoints)
│   ├── card_matcher.py         # OCR+SQL+CLIP matching pipeline
│   ├── card_detector.py        # OpenCV card detection
│   ├── yolo_card_detector.py   # YOLO-pose detection
│   ├── ocr.py                  # Tesseract/EasyOCR extraction
│   ├── recognizer.py           # CLIP-based recognizer (legacy)
│   ├── cardmarket_url.py       # Marketplace URL generation
│   ├── gemini_grade.py         # AI grading (Gemini Vision)
│   ├── gemini_identify.py      # Gemini-based identification
│   ├── text_index.py           # Text-based card search
│   ├── db.py                   # SQLite schema + queries
│   └── config.py               # Configuration
├── mobile/                     # React Native app
│   ├── app/                    # Expo Router screens
│   ├── src/                    # Components, stores, hooks, API, theme
│   └── package.json
├── scripts/                    # Data pipeline scripts
├── data/                       # Cards DB, images (gitignored)
├── models/                     # CLIP index, YOLO model (gitignored)
├── .claude/commands/           # Skill files for Claude Code agents
│   ├── card-engine.md
│   ├── defect-grader.md
│   └── mobile-dev.md
└── CLAUDE.md                   # This file
```

## Quick Start

```bash
# Backend
./venv/Scripts/python.exe -m uvicorn src.api:app --host 0.0.0.0 --port 8000

# Mobile
cd mobile && npx expo start
```

## API Endpoints

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

- **Production**: Hetzner 89.167.31.124, Docker at /opt/cardcheck/
- **Local Python**: always use `./venv/Scripts/python.exe` (has all deps)
- **Database**: SQLite WAL at data/cards.db (352MB)

## Current Priorities

1. Defect detection: add OpenCV layer to supplement Gemini grading
2. Mobile: real auth + cloud sync
3. Recognition: improve JP/TW OCR accuracy
4. Pricing: live price updates instead of daily snapshots
