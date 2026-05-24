---
type: api-endpoint
method: GET
path: /card/{tcgdex_id}/price-history
status: active
latency-p95: ~5ms
source: src/api.py:834-903
related: [[card-by-tcgdex-id-prices]], [[../modules/db]]
area: [backend, api, pricing]
tags: [api, pricing, history, time-series]
created: 2026-05-21
updated: 2026-05-21
---

# GET /card/{tcgdex_id}/price-history

> **TL;DR**: Time series цены карты — для построения price chart'ов в UI. Комбинирует наш `prices_external` snapshot data + legacy PokeTrace `price_history`.

## Request

| Param | In | Type | Default |
|-------|-----|------|---------|
| `tcgdex_id` | path | str | — |
| `marketplace` | query | str | "cardmarket" |
| `condition` | query | str | "NEAR_MINT" |
| `country` | query | str | "ALL" |
| `days` | query | int 1-365 | 90 |

## Response (`PriceHistoryResponse`)

```json
{
  "tcgdex_id": "sv04pt-EX005",
  "marketplace": "cardmarket",
  "condition": "NEAR_MINT",
  "country": "ALL",
  "data_points": [
    { "date": "2026-02-20", "avg": 11.50, "low": 7.00, "high": 22.00, "sale_count": 138 },
    { "date": "2026-02-21", "avg": 11.80, "low": 7.50, "high": 23.00, "sale_count": 142 },
    ...
  ]
}
```

## Pipeline

1. Verify card exists → 404 if not
2. **Source 1**: `price_history` table (legacy PokeTrace deep history) — если таблица существует
3. **Source 2**: `prices_external` (наши daily snapshots) — **overwrites** PokeTrace data за тот же day (наши данные приоритетнее)
4. Sort by date ASC
5. Return deduplicated time series

## Marketplace options

- `cardmarket` (default) — EU prices
- `tcgplayer` — US prices
- `ebay` — sold listings

## Condition options

- `NEAR_MINT` (default) — обычная
- `AGGREGATED` — все conditions
- `PSA_10`, `PSA_9`, `CGC_10`, ... — graded

## Country options (CardMarket only)

- `ALL` (default), `DE`, `FR`, `ES`, `IT`

## Failure modes

- 404: card не найдена
- 503: DB не загружена
- Возвращает пустой `data_points` если данных нет за period

## Performance

- ~1-5ms (один query)
- Bottleneck: deduplication между двух источников

## Use case

- Mobile: PriceHistoryChart component (recharts)
- Webapp: график на странице карты

## Связанные

- Current prices: [[card-by-tcgdex-id-prices]]
- Live pricing project: [[../../../10-Projects/2026-Q2-live-pricing]]
- Webapp issue (chart placeholder): [[../../08-webapp/known-issues#6-price-history-placeholder]]
