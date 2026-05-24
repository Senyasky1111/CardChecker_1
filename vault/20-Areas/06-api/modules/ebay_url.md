---
type: module
status: active
source: src/ebay_url.py
lines: 80
related: [[cardmarket_url]], [[../../03-pricing/sources/ebay]]
area: [backend, pricing]
tags: [module, url-generation, ebay]
created: 2026-05-21
updated: 2026-05-21
---

# ebay_url.py

> **TL;DR**: Генерирует eBay search URL с **sold + completed filters** для пользователя — чтобы видел реальные sold prices.

## Public surface

- `ebay_sold_url(card_dict) → str` — eBay sold-listings search URL
- `_clean_name(name) → str` — removes brackets, parenthetical notes

## Внутренняя логика

1. Pick name:
   - EN card → `name`
   - JP/TW → `eng_name`
2. Add language tag:
   - JP → "Japanese"
   - TW → "Chinese"
3. Add collector number formatted as "NNN/TTT"
4. Build query: `Pokemon [Japanese] CardName 006/078`

## eBay URL filters

- Category: 183454 (Pokemon Singles)
- `LH_Sold=1` — only sold listings
- `LH_Complete=1` — completed (для recency)
- Default sort: end date (most recent first)

## Зачем

- Free real-market price reference — eBay sold = real transactions
- Pull для UI кнопки "View on eBay"
- Используется в `_match_to_card()` для каждого identify

## Dependencies

- `urllib.parse`
- `re`

## Связанные

- CardMarket URLs: [[cardmarket_url]]
- eBay source doc: [[../../03-pricing/sources/ebay]]
- Module new: создан недавно (есть в свежей версии Desktop)
