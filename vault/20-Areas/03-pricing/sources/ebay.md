---
type: data-source
status: active
provider: eBay (sold listings scraping)
auth: none
rate-limit: throttled scraping
cost: free
created: 2026-05-21
updated: 2026-05-21
area: [pricing, data]
tags: [pricing, ebay, sold-listings]
related: [[../_MOC]], [[../../06-api/modules/ebay_url]]
---

# eBay (Sold Listings)

> **TL;DR**: Реальные **sold prices** (не asking) с eBay. Лучше отражает рынок чем asking prices. Free.

## What it provides

- **Sold listings** (completed transactions)
- Recent prices с timestamps
- Условие (часто missing/inconsistent)
- Real-market signal (asking vs sold gap может быть огромным)

## Access

- **Base URL**: `https://www.ebay.com`
- **Category**: 183454 (Pokemon Singles)
- **Filters**: `LH_Sold=1`, `LH_Complete=1`
- **Auth**: none (public scraping)
- **Rate limit**: throttled, friendly UA
- **Cost**: free

## URL pattern

```
https://www.ebay.com/sch/i.html?_nkw={query}&_sacat=183454&LH_Sold=1&LH_Complete=1
```

См. `_clean_name()` в `src/ebay_url.py` — query builder с language tagging (Japanese/Chinese).

## How we use it

### URL generation (for users)

`src/ebay_url.py` — генерирует URL для UI кнопки "View on eBay". User видит реальные recent sold listings.

### Price scraping

`scripts/scrape_ebay_photos.py` — собирает sold listings prices в `prices_external`:
- `marketplace = 'ebay'`
- `currency` зависит от listing (mostly USD)
- `condition` parsing best-effort (eBay's free-text descriptions)

### Phase 2: Direct URLs

`ebay_sold_listings` table — explicit direct URLs to specific sold listings. Phase 2 enrichment, не используется пока в primary path.

## Data quality issues

- **Condition parsing** ненадёжный — eBay description free-text
- **Fakes / replicas** в sold listings — outliers
- **Scalped Pokemon** events skew prices week-on-week
- → Use median price, не average; throw out top 5% и bottom 5%

## Why это важно

- **Free real-market signal** — sold prices > asking prices
- Покрывает обе marketplaces (US eBay, UK eBay, DE eBay)
- Free tier feature — все 3 (CardMarket + TCGPlayer + eBay) на free, чтобы пользователь видел ценность

## ToS

⚠️ eBay ToS forbids excessive automated scraping. Наш rate limit + sparing usage acceptable. **Не resale of raw data.**

## Связанные

- URL gen: [[../../06-api/modules/ebay_url]]
- Scraping: [[../../05-data-pipelines/ebay-scraping/photos]]
- Other sources: [[cardmarket]], [[pricecharting]], [[poketrace]]
