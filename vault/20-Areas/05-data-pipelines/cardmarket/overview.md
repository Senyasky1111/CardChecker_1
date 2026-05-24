---
type: note
status: stable
area: [data-pipelines, cardmarket]
tags: [cardmarket, scraping, pricing]
created: 2026-05-23
updated: 2026-05-23
---

# CardMarket Pipeline Overview

> Полная цепочка: scrape catalog → match с локальной DB → fill prices.

## Goal

CardMarket — primary EU pricing source + canonical product URLs для EN cards. У нас нужны: product URLs (для opening в app), images (для completeness), price points (EUR low/avg/trend).

## Pipeline stages

```
1. scrape_cm_all_products.py     → products_singles.json (catalog)
2. download_cardmarket_csvs.py   → cards_with_prices.json (parsed)
3. fetch_cardmarket_urls.py      → construct URLs from card names
4. match_cm_products.py          → fuzzy-match catalog ↔ local DB
5. scrape_cardmarket_images.py   → download product images
6. fill_prices_from_csv.py       → write prices to DB
7. _fix_duplicate_cmids.py       → cleanup duplicates
```

См. [[../scripts-catalog#CardMarket (7)|scripts-catalog]] для размеров.

## Outputs

- `cards.cardmarket_product_id` column populated
- `cards.cardmarket_url` populated
- `prices` table: EUR low/avg/trend per card
- `data/cards/<set>/<card>.jpg` images downloaded

## Failure modes

- **CM blocks scraping** — rate-limit 1.5s per request, 3 workers. Если CM меняет anti-scraping → pipeline breaks. No graceful degrade.
- **Product not found** — many JP/TW cards отсутствуют в CM catalog. Logged, skipped.
- **Duplicate matches** — fuzzy match returns 2+ candidates. `_fix_duplicate_cmids.py` post-processes.

## Frequency

- **Catalog scrape**: monthly (CM adds new sets)
- **CSV / price update**: daily (через [[../runbooks/daily-price-update]])
- **Image scrape**: as needed (manual; image set rarely changes per card)

## Coverage

EN cards: ~95% have CM URLs.
JP cards: ~60% (CM JP coverage uneven).
TW cards: ~30% (small CM TW market).

## Related

- URL construction: [[../../06-api/modules/cardmarket_url]]
- Pricing source detail: [[../../03-pricing/sources/cardmarket]]
- [[../scripts-catalog]]
