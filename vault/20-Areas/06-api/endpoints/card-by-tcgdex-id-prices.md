---
type: api-endpoint
method: GET
path: /card/{tcgdex_id}/prices
status: active
latency-p95: ~5ms
source: src/api.py:705-811
related: [[../modules/db]], [[../../03-pricing/_MOC]]
area: [backend, api, pricing]
tags: [api, pricing, multi-source]
created: 2026-05-21
updated: 2026-05-21
---

# GET /card/{tcgdex_id}/prices

> **TL;DR**: Multi-source pricing: CardMarket (по странам), TCGPlayer, eBay, graded (PSA/CGC). Это **главный** pricing endpoint для UI.

## Request

| Param | In | Type | Default |
|-------|-----|------|---------|
| `tcgdex_id` | path | str | — |

Пример: `/card/sv04pt-EX005/prices`

## Response (`PriceDetail`)

```json
{
  "tcgdex_id": "sv04pt-EX005",
  "name": "Charizard ex",
  "set_name": "Paldea Evolved",
  "language": "en",
  "cardmarket": {
    "near_mint": { "avg": 12.50, "low": 8.00, "high": 25.00, "sale_count": 142 },
    "near_mint_de": { ... },
    "near_mint_fr": { ... },
    "near_mint_es": { ... },
    "near_mint_it": { ... }
  },
  "tcgplayer": {
    "near_mint": { "avg": 15.20 },
    "aggregated": { ... }
  },
  "ebay": {
    "near_mint": { ... },
    "aggregated": { ... }
  },
  "graded": {
    "psa_10": { "avg": 450, "sale_count": 23 },
    "psa_9": { ... },
    "cgc_10": { ... }
  },
  "links": {
    "cardmarket": "https://...",
    "tcgplayer": "https://...",
    "pricecharting": "https://...",
    "ebay": "https://..."
  },
  "last_updated": "2026-05-20T18:30:00Z"
}
```

## Pipeline

1. Lookup card by `tcgdex_id` в `cards` table → 404 if not found
2. `SELECT * FROM prices_external WHERE tcgdex_id = ? ORDER BY snapshot_date DESC`
3. Group prices by:
   - **CardMarket** — condition + country (`near_mint`, `near_mint_de`, `near_mint_all`...)
   - **TCGPlayer** — condition only
   - **eBay** — condition only
   - **Graded** — `psa_10`, `psa_9`, `cgc_10`...
4. Build URLs: CardMarket (locale-aware), TCGPlayer (stored или generated), PriceCharting (stored или generated), eBay sold
5. Return organised tree

## Failure modes

- 404: Card не найдена в `cards` table
- 503: DB не загружена

## Performance

- ~1-5ms (single SQL query на `prices_external`)
- Никаких external API calls (всё закешировано daily)

## Связанные

- Pricing MOC: [[../../03-pricing/_MOC]]
- Sources: [[../../03-pricing/sources/cardmarket]], [[../../03-pricing/sources/pricecharting]]
- Refresh job: [[../../05-data-pipelines/price-refresh-daily]]
- History: [[card-by-tcgdex-id-price-history]]
