---
type: api-endpoint
method: GET
path: /card/{id_product}
status: legacy
latency-p95: <1ms
source: src/api.py:656-684
related: [[../modules/recognizer]], [[../modules/cardmarket_url]]
area: [backend, api]
tags: [api, card-detail, cardmarket, legacy]
created: 2026-05-21
updated: 2026-05-21
---

# GET /card/{id_product}

> **TL;DR**: Legacy endpoint — карта по CardMarket id_product. Возвращает базовые поля + URL'ы CardMarket для 5 локалей.
> Для новой работы используй [[card-by-tcgdex-id-prices]] (более полный данные).

## Request

| Param | In | Type | Default |
|-------|-----|------|---------|
| `id_product` | path | int | — |
| `locale` | query | str | "en" |

## Response (`CardDetailResponse`)

```json
{
  "id_product": 12345,
  "name": "Charizard ex",
  "expansion_name": "Pokémon GO",
  "expansion_id": 5021,
  "price_trend": 8.50,
  "price_low": 4.20,
  "price_avg": 6.75,
  "price_foil_trend": 0,
  "cardmarket_url": "https://www.cardmarket.com/en/Pokemon/Products/Singles/...",
  "cardmarket_urls": {
    "en": "...",
    "it": "...",
    "de": "...",
    "fr": "...",
    "es": "..."
  }
}
```

## Pipeline

1. `_get_recognizer()` (DI, 503 if None)
2. `rec.get_card(id_product)` → lookup в CLIP index
3. `card_url(card, locale=...)` для 5 локалей
4. Return

## Failure modes

| Code | When |
|------|------|
| 404 | Карта не в CLIP индексе |
| 503 | CLIP не загружен |

## Что не возвращает (и почему legacy)

- ❌ tcgdex_id
- ❌ TCGPlayer / PriceCharting / eBay URL'ы
- ❌ Graded prices (PSA/CGC/BGS)
- ❌ Multi-source aggregated pricing

→ Для всего этого использовать [[card-by-tcgdex-id-prices]].

## Связанные

- Modern alternative: [[card-by-tcgdex-id-prices]]
- Module: [[../modules/cardmarket_url]]
