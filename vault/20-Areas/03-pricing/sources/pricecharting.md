---
type: data-source
status: active
provider: PriceCharting
auth: none
rate-limit: ~3 req/s with throttling
cost: free
area: [pricing, data]
tags: [pricing, pricecharting]
source: scripts/build_pricecharting_map.py
related: [[../url-mapping/coverage-status]], [[../../05-data-pipelines/pricecharting-pipeline/build-mapping]]
---

# PriceCharting

> **TL;DR**: Free price source. Хорошее покрытие EN (95%), среднее JP (66%), низкое TW (62%).
> Платформенные ограничения не позволят достичь 100%.

## What it provides

- Цены ungraded / graded карт (PSA 7-10, BGS, CGC)
- Sold listings (eBay data)
- Прямые URL'ы карт по схеме: `/game/pokemon-{set-slug}/{card-slug}-{num}`

## Access

- **Base URL**: `https://www.pricecharting.com`
- **Auth**: none
- **Rate limit**: throttling ~3 req/s
- **Cost**: free

## Coverage

| Language | Cards in DB | Direct URLs | % |
|----------|-------------|-------------|---|
| EN | 20,406 | 19,426 | **95.2%** |
| JP | 15,725 | 10,330 | **65.7%** |
| TW | 12,366 | 7,678 | **62.1%** |

## Почему не 100%?

- PriceCharting каталогизирует **только ~126 JP sets** из наших 261 set_ids
  - Старые JP sets (DP1-5, BW, XY sub-sets, promo) **не на PriceCharting**
- Только **14 Chinese sets** из наших 119 TW set_ids
- **Platform limitations, не fixable on our side**

## Trick: JP URL → TW card

Поскольку TW и JP версии часто одинаковые → **скопировали JP direct URL'ы для матчащих TW карт без своего PC set**. Это подняло TW покрытие.

## How we use it

### Build mapping

`scripts/build_pricecharting_map.py` — словари slug'ов sets:
- `EN_SET_SLUGS` — английские sets
- `JP_SET_SLUGS` — ~110 JP мапингов (SV starters, S&S, SM, ME, XY, BW, DP/Pt, HGSS eras)
- `TW_SET_SLUGS` — 14 Chinese set мапингов

### Validate URLs

`scripts/resolve_pricecharting_urls.py` — comprehensive approach:
1. Generate direct URL из mapping
2. HTTP validate (HEAD request)
3. Если 404 → search fallback (`/search-products?q=...`)

~0.3s per card с rate limiting → **1-2 часа per language**.

### Auto-discover sets

`scripts/scrape_pc_sets.py` — автоматически находит новые PC sets с category page.

## Data quality issues

- Маппинг set name → slug ручной (ошибки возможны при добавлении новых sets)
- Цены **не real-time** — обновляются раз в день
- Graded prices для редких карт могут быть out of date

## Refresh

```bash
# Re-validate всех URLs одного языка (1-2 часа)
./venv/Scripts/python.exe scripts/resolve_pricecharting_urls.py --validate --lang ja
./venv/Scripts/python.exe scripts/resolve_pricecharting_urls.py --validate --lang zh-tw

# Затем deploy DB на сервер
scp data/cards.db root@89.167.31.124:/opt/cardcheck/data/cards.db
ssh root@89.167.31.124 "cd /opt/cardcheck && docker compose restart"
```

См. [[../../10-infrastructure/deploy-procedure]] про деплой.

## ToS / Legal

⚠️ Проверить ToS на scraping. Низкий rate limit + честный UA должны быть OK для нашего use case (price aggregation для приложения, не reselling данных).

## Связанные

- Pipeline: [[../../05-data-pipelines/pricecharting-pipeline/build-mapping]]
- URL mapping strategy: [[../url-mapping/pricecharting-mapping-strategy]]
- Coverage status: [[../url-mapping/coverage-status]]
- Other sources: [[cardmarket]], [[poketrace]], [[pokemon-api-rapidapi]]
