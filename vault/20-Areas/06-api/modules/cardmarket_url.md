---
type: module
status: active
source: src/cardmarket_url.py
lines: 158
related: [[ebay_url]], [[../../03-pricing/sources/cardmarket]]
area: [backend, pricing]
tags: [module, url-generation, cardmarket]
created: 2026-05-21
updated: 2026-05-21
---

# cardmarket_url.py

> **TL;DR**: Генерирует CardMarket search / product URLs для идентифицированной карты. Multi-locale (en/de/fr/es/it/pl/jp/nl/pt/se).

## Public surface

- `card_url(card_dict, locale='en') → str` — best available:
  - Priority 1: idProduct redirect (если `cm_id_product`)
  - Priority 2: search URL (fallback с name/set/number)
- `search_url(card_name, expansion_id, locale) → str` — direct search
- `card_urls_multi_locale(card_dict, locales=['en','it','de','fr']) → dict[locale, url]`
- `_clean_card_name(name) → str` — strips ability text, set numbers

## Internal flow

1. Prefer direct product ID link (1 request, instant)
2. Fallback: search query с:
   - Cleaned name
   - Set abbreviation
   - Collector number
   - Expansion_id (только для EN — CardMarket не знает tcgdex codes для JP/TW)
3. Language-aware:
   - EN cards → `name`
   - JP/TW cards → `eng_name`
4. Filter expansion_id только для EN

## CardMarket specifics

- Category 51 = Pokemon Singles
- Locale codes: `en`, `de`, `fr`, `es`, `it`, `jp`, `nl`, `pl`, `pt`, `se`

## URL cleaning

Removes:
- `[ability]` brackets
- `(NNN/MMM)` parens
- `(notes)` parens

## Dependencies

- `urllib.parse.urlencode`
- `re`

## Использование

- `api.py:_match_to_card()` — для каждого identify результата
- `api.py:_get_recognizer().get_card()` legacy endpoint
- `recognizer.py` для возвращаемых cards

## Связанные

- eBay URLs: [[ebay_url]]
- CardMarket source doc: [[../../03-pricing/sources/cardmarket]]
- API endpoint: [[../endpoints/card-by-id-product]]
