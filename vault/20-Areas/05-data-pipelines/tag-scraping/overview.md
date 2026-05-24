---
type: module
status: active
created: 2026-05-21
updated: 2026-05-21
area: [data, ml]
tags: [scraping, tag-grading, defect-detection]
source: scripts/scrape_tag.py
related: [[cdn-migration-cloudfront]], [[current-state]], [[runbook-re-scrape]]
---

# TAG Scraping Pipeline

> **TL;DR**: Скрапим публичные TAG DIG reports для defect detection training. Source-of-truth для grading ground truth.
> Текущее: 96,551 cards в `data/tag_raw/`, 423 GB raw data, ~120 GB processed dataset.

## Что мы скрапим

- **DIG reports**: `my.taggrading.com/card/{CERT#}` — публичные отчёты
- **Pop report**: `my.taggrading.com/pop-report` — discovery cert номеров
- TAG — это **SPA без публичного API**, скрапим через Playwright

## Сколько собрано

| Метрика | Значение |
|---------|----------|
| Cert-папок в `data/tag_raw/` | 96,551 |
| Cards в `scraper.db.cards` | 115,535 |
| Cert discovery records | 457,110 |
| Disk: tag_raw | 423 GB |
| Disk: tag_dataset (YOLO format) | 96 GB |
| Disk: tag_dataset_1280 (resized) | 11 GB |

## Что в каждом cert

```
data/tag_raw/{CERT#}/
├── metadata.json        # все поля из DIG report
└── images/              # HD photos
    ├── FRONT_MAIN.jpg
    ├── BACK_MAIN.jpg
    └── ...crops
```

## State management

`data/scraper.db` (SQLite, 89 MB):
- `cards` (115K rows) — main scraping queue
- `cert_discovery` (457K rows) — discovered cert numbers
- `discovery_progress` (28K rows) — pagination state

Статусы карт: `pending` → `discovered` → `scraped` → `done` (с downloaded images).

## Известные проблемы

### CDN migration (2026-05-13) — см. [[cdn-migration-cloudfront]]

TAG переехал с S3 на CloudFront. Скрапер фильтровал по `s3.us-west` — после миграции **захватывал 0 image URLs**, но grades/defects работали.

**Last impact**: ~19,801 cards со `status='scraped'` имеют пустые `s3_image_urls` — нужно re-scrape.

### Что НЕ даёт TAG

- НЕТ pixel-level defect coordinates (только text descriptions = DINGS)
- НЕТ bounding boxes
- Card Vision = raw surface topology, не labeled heatmap
- Маски нужно извлекать через diff+threshold+contours

## Запуск

```bash
# Discovery (если нужны новые cert номера)
./venv/Scripts/python.exe scripts/scrape_tag.py --discover

# Scraping (основной workflow)
./venv/Scripts/python.exe scripts/scrape_tag.py --scrape

# Download images (если scrape работал, а download нет)
./venv/Scripts/python.exe scripts/scrape_tag.py --download
```

## Build YOLO dataset из tag_raw

После скрапинга есть отдельный шаг — сборка YOLO-формата:

```bash
./venv/Scripts/python.exe scripts/scrape_tag.py --build-dataset
```

Создаёт `data/tag_dataset/{images,labels}/{train,val,test}/`.

## Известные edge cases

- Cert номера могут начинаться с разных букв (C, V, U, D, L, Q, R...) — не префиксы
- Некоторые карты имеют 5+ фото (corner crops, defect crops, slab photos)
- Pop report имеет infinite scroll — нужна пагинация через нажатие кнопок

## Связанные

- Recovery runbook: [[runbook-re-scrape]]
- CDN история: [[cdn-migration-cloudfront]]
- Текущее состояние: [[current-state]]
- Defect detection: [[../../02-grading/defect-detection/architecture]]
- ML training: [[../../09-ml-research/defect-yolo/strategy]]
