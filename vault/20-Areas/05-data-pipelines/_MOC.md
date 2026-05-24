---
type: moc
status: active
created: 2026-05-21
updated: 2026-05-23
area: [data, backend]
tags: [moc, scraping, etl]
---

# Data Pipelines MOC

> Все 57 scripts из `scripts/`. Каталог + под-MOC'и + runbooks.

## Master catalog

- [[scripts-catalog]] — **inventory всех 57 scripts** с одним предложением каждый. Start here.

## Sub-area overviews

- [[cardmarket/overview]] — full CM pipeline (catalog → match → prices)
- [[pricecharting/overview]] — URL discovery + fuzzy matching
- [[ebay-scraping/overview]] — scraped real-world photos для training data
- [[tag-scraping/overview]] — TAG grading reports → defect detection dataset
- [[tag-scraping/cdn-migration-cloudfront]] — history: S3 → CloudFront incident

## Runbooks

- [[runbooks/daily-price-update]] — scheduled daily refresh (Windows Task Scheduler)

## Database build

`scripts/build_card_database.py` — full DB rebuild from TCGdex. См. [[scripts-catalog#Database Building (4)]].

## Training data pipelines

См. [[../09-ml-research/_MOC]]:
- YOLO synthetic dataset: [[../09-ml-research/yolo-card-detection/dataset]]
- CLIP pairs: [[../09-ml-research/clip-finetuning/pairs-generation]]
- Defect dataset (from TAG): [[../09-ml-research/defect-yolo/training]]

## Связанные

- Pricing source coverage: [[../03-pricing/_MOC]]
- Catalog / DB schema: [[../04-catalog/_MOC]]
- API modules: [[../06-api/_MOC]]

## ADRs in this area

- [[../../30-Resources/adr/2026-05-23-pricecharting-fuzzy-match-thresholds]]
- [[../../30-Resources/adr/2026-02-15-sqlite-not-postgres]]
