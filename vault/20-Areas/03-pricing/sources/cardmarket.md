---
type: data-source
status: active
provider: CardMarket
auth: none (scraping) / API for some endpoints
rate-limit: throttled scraping ~2 req/s
cost: free
created: 2026-05-21
updated: 2026-05-21
area: [pricing, data]
tags: [pricing, cardmarket, eu]
related: [[../_MOC]], [[../../06-api/modules/cardmarket_url]]
---

# CardMarket

> **TL;DR**: Главный pricing source для EU market. EUR prices. Огромный database для EN, slabber для JP/TW.

## What it provides

- Цены ungraded (NM/EX/GD/LP/PL/PO conditions)
- Цены по странам (DE, FR, ES, IT, ALL)
- Foil pricing
- Price trends (avg, low, high)
- Multi-locale URLs (en/de/fr/es/it/pl/jp/nl/pt/se)

## Access

- **Base URL**: `https://www.cardmarket.com`
- **Category** для Pokemon: `51` (Pokemon Singles)
- **Auth**: none (для public scraping). Есть и платный API но мы его не используем.
- **Rate limit**: throttled scraping ~2 req/s
- **Cost**: free

## URL types

### idProduct redirect (priority 1)

```
https://www.cardmarket.com/{locale}/Pokemon/Products/Singles/{anything}/{id_product}
```

CardMarket автоматически редиректит на правильную страницу по product ID. Стабильно, не ломается на rename.

### Search URL (fallback)

```
https://www.cardmarket.com/{locale}/Pokemon/Products/Search?searchString=...&category=51
```

Когда нет `cm_id_product` — фоллбэк на search query с cleaned name + set + number.

См. [[../../06-api/modules/cardmarket_url]] для деталей generation.

## Coverage

- **EN cards**: огромное покрытие, у нас 95%+ с direct id_product
- **JP cards**: умеренное (CardMarket для JP в основном search-based)
- **TW cards**: слабое

## Data quality issues

- Old card variations иногда unmapped → нужно fallback на search
- Cardholder может вручную исправлять mapping для popular cards

## How we use it

### URL generation
- `src/cardmarket_url.py` — генерирует URL'ы для каждой identified карты
- 5 locales (en/de/fr/es/it) by default

### Price scraping
- `scripts/scrape_cardmarket_images.py` — фото карт для recognition
- `scripts/scrape_cm_all_products.py` — массовая sync с CardMarket
- `scripts/fetch_cardmarket_urls.py` — заполнение `cm_id_product` для cards в DB

### Storage
- `cards.cm_id_product` — id для direct redirect
- `prices` table — старый snapshot (legacy)
- `prices_external` table — current source с country breakdown

## Refresh

- `scripts/update_prices_daily.py` — daily job на сервере
- Cron schedule на Hetzner: ежедневно 06:00 UTC
- Updates `prices_external` table в DB

## ToS / Legal

⚠️ CardMarket ToS forbids excessive scraping. Наш rate limit ~2 req/s acceptable для personal/aggregator use. **Не reseling raw data.**

Если start commercial scaling — рассмотри их paid API.

## Связанные

- URL gen module: [[../../06-api/modules/cardmarket_url]]
- Scraping scripts: [[../../05-data-pipelines/cardmarket-scraping/scrape-products]]
- Daily refresh: [[../../05-data-pipelines/price-refresh-daily]]
- Other sources: [[pricecharting]], [[poketrace]], [[ebay]]
