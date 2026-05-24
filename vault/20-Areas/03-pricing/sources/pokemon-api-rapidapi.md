---
type: data-source
status: active
provider: Pokemon TCG API (via RapidAPI)
auth: API key (POKEMON_API_RAPIDAPI_KEY)
rate-limit: 300 req/min (~5 req/s) → we use 4 req/s
cost: paid (RapidAPI subscription)
created: 2026-05-21
updated: 2026-05-21
area: [pricing, data]
tags: [pricing, pokemon-tcg-api, rapidapi, us]
related: [[../_MOC]], [[../../06-api/modules/config]]
---

# Pokemon TCG API (via RapidAPI)

> **TL;DR**: Третий paid pricing source. **TCGPlayer USD prices** + некоторые graded prices. Поднимает покрытие US market.

## What it provides

- **TCGPlayer prices** (USD) — основная ценность
- Some graded prices (overlap с PokeTrace)
- Card metadata enrichment
- Condition breakdowns

## Access

- **Base URL**: `https://pokemon-tcg-api.p.rapidapi.com` (из `config.py`)
- **Auth**: `POKEMON_API_RAPIDAPI_KEY` в `.env`
- **Rate limit**: 300 req/min → `POKEMON_API_DELAY = 0.25s` (~4 req/s, headroom)
- **Cost**: RapidAPI subscription

## Coverage

- EN cards: высокое (US-focused)
- JP cards: ограниченное
- TW: minimal

## How we use it

Stored в `prices_external`:
- `marketplace = 'tcgplayer'`
- `currency = 'USD'`
- `condition` varies (near_mint, lightly_played, etc.)

Linked через `card_external_ids` table (`tcgplayer_id`).

### URL generation

См. `_build_tcgplayer_url()` в `src/api.py:408-418`:
- Если в DB stored TCGPlayer URL → use it
- Иначе fallback на product ID-based URL pattern

## Refresh

Через `update_prices_daily.py` — параллельно с PokeTrace и CardMarket.

## Зачем нужен (помимо PokeTrace и CardMarket)

- **TCGPlayer = US market** — CardMarket это EU, PokeTrace tend to aggregate. US пользователи хотят видеть TCGPlayer.
- Free price source в Free tier (вместе с CardMarket + eBay — все 3 на Free, см. [[../../11-product/monetization/tiers-free-plus-pro]])

## Связанные

- Config: [[../../06-api/modules/config]]
- Daily refresh: [[../../05-data-pipelines/price-refresh-daily]]
- Other sources: [[cardmarket]], [[pricecharting]], [[poketrace]], [[ebay]]
