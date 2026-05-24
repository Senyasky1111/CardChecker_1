---
type: data-source
status: active
provider: PokeTrace
auth: API key (POKETRACE_API_KEY)
rate-limit: 30 req / 10s (~3 req/s)
cost: paid (per-month subscription, точная сумма в .env)
created: 2026-05-21
updated: 2026-05-21
area: [pricing, data]
tags: [pricing, poketrace, graded, history]
related: [[../_MOC]], [[../../06-api/modules/config]]
---

# PokeTrace

> **TL;DR**: Paid API. Главная ценность — **graded prices** (PSA 10, PSA 9, CGC 10, BGS) и **historical pricing** (deep history).

## What it provides

- **Graded prices**: PSA 10, PSA 9, PSA 8, CGC 10, CGC 9, BGS 10, BGS 9.5
- **Deep price history** — много месяцев истории (наш `price_history` table берёт оттуда legacy)
- **Sale counts** per period
- Aggregated by condition
- USD prices

## Access

- **Base URL**: `https://api.poketrace.com/v1` (из `config.py`)
- **Auth**: `POKETRACE_API_KEY` в `.env`
- **Rate limit**: 30 req / 10s → mы используем burst delay `POKETRACE_BURST_DELAY = 0.35s` (~3 req/s, safe)
- **Cost**: paid subscription

## Coverage

- EN cards: высокое
- JP/TW: умеренное

## How we use it

### Storage tables

- `prices_external` — daily snapshots (condition, country, currency)
- `price_history` — legacy deep history (PokeTrace `/history` endpoint)
- `card_external_ids` — mapping наших `tcgdex_id` → PokeTrace IDs

### Refresh

`scripts/update_prices_daily.py` — daily job:
1. Поднять список cards с PokeTrace mapping
2. Запросить current prices с rate limiting
3. Insert в `prices_external` с `snapshot_date = today`

### Why graded prices важны

- **Pro tier paywall trigger** (см. [[../../11-product/monetization/tiers-free-plus-pro]])
- ROI calculator на mobile/webapp использует graded values
- "Стоит ли подавать на PSA?" — главный сценарий

## Data quality issues

- Иногда сильные outliers в graded prices (один dealer накручивает)
- Sale count метрики надёжнее avg price для thin markets

## Rate limits

Compliance:
- `POKETRACE_BURST_DELAY = 0.35s` (config.py) — ~3 req/s
- Within their 30 req / 10s window with headroom

## ToS

✅ Paid API — официальный use. Подписку не публикуем.

## Связанные

- Config: [[../../06-api/modules/config]]
- Daily refresh: [[../../05-data-pipelines/price-refresh-daily]]
- Pricing endpoint: [[../../06-api/endpoints/card-by-tcgdex-id-prices]]
- Monetization tie: [[../../11-product/monetization/tiers-free-plus-pro]]
- Other sources: [[cardmarket]], [[pricecharting]], [[pokemon-api-rapidapi]]
