---
type: data-source
status: indirect
provider: TCGPlayer (accessed via Pokemon TCG API)
auth: indirect
rate-limit: indirect (via RapidAPI)
cost: indirect
created: 2026-05-21
updated: 2026-05-21
area: [pricing, data]
tags: [pricing, tcgplayer, us]
related: [[../_MOC]], [[pokemon-api-rapidapi]]
---

# TCGPlayer

> **TL;DR**: US-focused price source. Мы **не** скрапим напрямую — получаем через [[pokemon-api-rapidapi]] (RapidAPI proxy).

## Что это

TCGPlayer — крупнейший US trading card marketplace. Главная альтернатива CardMarket для US users.

## Как мы получаем

**Indirect** через [[pokemon-api-rapidapi]] — у них есть TCGPlayer integration. Мы не имеем direct TCGPlayer API.

## URL generation

Direct linking к TCGPlayer cards (для UI кнопки):
- См. `_build_tcgplayer_url()` в `src/api.py:408-418`
- Stored URLs в `cards.tcgplayer_url` (если есть)
- Fallback: pattern `https://www.tcgplayer.com/product/{tcgplayer_id}`

## Storage

В `cards`:
- `tcgplayer_id` (через `card_external_ids` table)
- `tcgplayer_url` (если direct URL known)

В `prices_external`:
- `marketplace = 'tcgplayer'`
- `currency = 'USD'`
- Source через RapidAPI

## Coverage

- EN cards: высокое
- JP/TW: minimal (TCGPlayer US-focused)

## Why это важно

- **US market** — для US users CardMarket prices в EUR not useful
- TCGPlayer = de-facto US pricing standard
- Free tier feature (вместе с CardMarket + eBay) — см. [[../../11-product/monetization/tiers-free-plus-pro]]

## Future considerations

- Direct TCGPlayer API would be ideal — у них есть paid API но мы пока не на их volume tier
- Если scaling US user base — рассмотри подписку

## Связанные

- Indirect access: [[pokemon-api-rapidapi]]
- Other sources: [[cardmarket]], [[pricecharting]], [[poketrace]], [[ebay]]
- Pricing endpoint: [[../../06-api/endpoints/card-by-tcgdex-id-prices]]
