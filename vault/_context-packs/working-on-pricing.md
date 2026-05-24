---
type: context-pack
status: active
created: 2026-05-21
updated: 2026-05-21
tags: [context-pack, pricing]
---

# Context Pack: Working on Pricing

> **Use when**: Работаешь с pricing pipeline, URL mapping, новые источники цен, refresh.

## Pricing MOC

![[../20-Areas/03-pricing/_MOC]]

## Active source: PriceCharting

![[../20-Areas/03-pricing/sources/pricecharting]]

## Project

- [[../10-Projects/2026-Q2-live-pricing]] — Q2 priority #4

## Pipeline scripts

- `scripts/build_pricecharting_map.py` — slug mappings
- `scripts/resolve_pricecharting_urls.py` — HTTP validation
- `scripts/scrape_pc_sets.py` — auto-discover PC sets
- `scripts/scrape_cardmarket_images.py`
- `scripts/scrape_cm_all_products.py`
- `scripts/fetch_cardmarket_urls.py`
- `scripts/update_prices_daily.py` — daily refresh job

## Database

- `data/cards.db` — таблицы prices/cardmarket_urls/pricecharting_urls

## Что важно помнить

- PriceCharting **не покроет** старые JP/TW sets — platform limitation
- TW cards без своего PC set → используют JP direct URL
- Деплой DB-only: `scp data/cards.db ... && docker compose restart`
- Rate limit ~3 req/s
