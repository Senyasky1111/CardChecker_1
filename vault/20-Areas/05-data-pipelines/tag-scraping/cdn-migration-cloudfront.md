---
type: module
status: resolved
created: 2026-05-21
updated: 2026-05-21
incident-date: 2026-05-13
area: [data, ml]
tags: [scraping, tag-grading, cdn, incident]
source: scripts/scrape_tag.py
related: [[overview]], [[current-state]]
---

# TAG CDN Migration — S3 → CloudFront

> **TL;DR** (2026-05-13): TAG переехал с S3 на CloudFront. Скрапер был жёстко завязан на `s3.us-west` и тихо переставал скачивать картинки. **~19.8K карт собрано в этот buggy период** и нужно re-scrape.

## Что произошло

TAG Grading переместил фотографии карт:
- **Старо**: `devblock-tag.s3.us-west-2.amazonaws.com`
- **Ново**: `d39lwrz0lm7c9r.cloudfront.net`

Произошло где-то **до середины April 2026**.

## Что сломалось

Image URL filter в скрапере был литералом:
```python
s.includes('s3.us-west')  # старый код
```

После миграции **все новые scrape'ы захватывали 0 image URLs**. Но:
- `surface_defects` поля работали ✅
- `grade` поля работали ✅
- HTML парсинг работал ✅
- **Только image URLs возвращались пустыми** ❌

## Почему долго не замечали

- Ошибок не было — DOM просто возвращал пустой list
- Pipeline продолжал работать, status='scraped' выставлялся
- Реальная проблема видна только на download phase: некуда скачивать
- Метрики scrape rate выглядели нормально

## Как поняли

Запрос check: `page.evaluate("[...document.querySelectorAll('img')].map(i => i.src)")` на один cert — увидел CloudFront URL'ы.

## Fix

Изменили селектор с literal `s3.us-west` на path-based:
```python
'/card-images/'  # новый код
```

Path `/card-images/` присутствует **и в старых S3 URL'ах, и в новых CloudFront** — backward compatible.

## Damage to clean up

**~19,801 cards** застряли в:
- `status = 'scraped'`
- `s3_image_urls = []` (пусто)
- `image_uuid IS NULL`

Скрапились между **2026-03-22 и 2026-05-01** (buggy window).

### Recovery SQL

```sql
-- in data/tag_raw/scraper.db
UPDATE cards
SET status='pending',
    scraped_at=NULL,
    metadata_json=NULL,
    tag_score=0,
    grade=0,
    num_defects=0
WHERE status='scraped';
```

Затем re-scrape с фикснутым кодом. См. [[runbook-re-scrape]].

### Что НЕ затронуто

**29,181 cards** со `status='done'` — fine. Они скрапились **до** CDN миграции, имеют валидные (хоть и теперь stale, но S3-сервер всё равно отдаёт) URL'ы и уже скачанные images на диске.

## Lessons

- **Скрапинг SPA без API хрупкий** — любое изменение CDN/хоста ломает молча
- Нужен **monitoring** — если image count резко падает, alert
- Selector'ы должны быть **path-based**, не host-based, где возможно

## Если повторится

1. Run quick diag: `page.evaluate("[...document.querySelectorAll('img')].map(i => i.src)")` на один cert URL
2. Найди новый CDN host
3. Если path `/card-images/` сохранился — селектор должен сам подхватить
4. Если нет — обновить селектор, запустить recovery SQL

## Связанные

- [[overview]]
- [[current-state]]
- [[runbook-re-scrape]]
- Файл: `scripts/scrape_tag.py` — `S3_BASE` const + image selector в `scrape_card_report()`
