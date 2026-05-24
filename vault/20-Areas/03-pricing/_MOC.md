---
type: moc
status: active
created: 2026-05-21
updated: 2026-05-21
area: [pricing, backend]
tags: [moc, pricing]
---

# Pricing MOC

> Откуда берём цены и как агрегируем.
> Сегодня: daily snapshots в `data/cards.db`. Roadmap: live prices.

## Стратегия

- [[strategy]] — какие источники и почему

## Источники

- [[sources/cardmarket]] — основной для EN (idProduct redirect, search URL для JP/TW)
- [[sources/pricecharting]] — coverage: EN 95% / JP 66% / TW 62%
- [[sources/poketrace]]
- [[sources/pokemon-api-rapidapi]]
- [[sources/tcgplayer]]
- [[sources/ebay]] — `scripts/scrape_ebay_photos.py`

## URL Mapping (PriceCharting)

- [[url-mapping/pricecharting-mapping-strategy]]
- [[url-mapping/coverage-status]] — текущая статистика
- [[url-mapping/validation-process]]

## Refresh

- [[refresh-cadence]] — daily snapshots, как и когда
- [[live-pricing-plan]] — roadmap для real-time

## Связанные

- Pipelines: [[../05-data-pipelines/cardmarket-scraping/scrape-products]]
- Pipelines: [[../05-data-pipelines/pricecharting-pipeline/build-mapping]]
- API: [[../06-api/endpoints/card-{id}-prices]]
- Каталог: [[../04-catalog/_MOC]]
