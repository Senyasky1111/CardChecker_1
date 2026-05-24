---
type: context-pack
status: active
created: 2026-05-21
updated: 2026-05-21
tags: [context-pack, debugging, tag-scraping]
---

# Context Pack: Debugging TAG Scraper

> **Use when**: TAG scraper не работает / image counts падают / нужно re-scrape / новый CDN.

## Что мы знаем про TAG

![[../20-Areas/05-data-pipelines/tag-scraping/overview]]

## Известный incident: CDN migration

![[../20-Areas/05-data-pipelines/tag-scraping/cdn-migration-cloudfront]]

## Debugging steps

### 1. Quick check — image URLs возвращаются?

```python
# Запустить на один cert URL через Playwright
page.evaluate("[...document.querySelectorAll('img')].map(i => i.src)")
```

Должны быть URL'ы с `/card-images/` в пути.

### 2. Проверить state DB

```bash
sqlite3 data/scraper.db "SELECT status, COUNT(*) FROM cards GROUP BY status"
```

Если много `scraped` без `done` — значит download phase сломан.

### 3. Recovery SQL — если опять CDN сменилось

```sql
UPDATE cards
SET status='pending',
    scraped_at=NULL,
    metadata_json=NULL,
    tag_score=0,
    grade=0,
    num_defects=0
WHERE status='scraped';
```

Затем re-scrape с фикснутым селектором.

## Code locations

- `scripts/scrape_tag.py` — main scraper
- `S3_BASE` const + image selector в `scrape_card_report()` — где жил баг
- `DATA_DIR = Path("data/tag_raw")` — путь к сохранению
- `DATASET_DIR = Path("data/tag_dataset")` — путь к YOLO формату

## Disk impact

- 96,551 cert × ~4 фото = ~400K фото = 423 GB
- Подумай **дважды** прежде чем триггерить full re-scrape

## Skill

`/data-engineer` — для глубоких вопросов по pipeline architecture.
