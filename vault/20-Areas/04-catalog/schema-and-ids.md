---
type: note
status: stable
area: [catalog, database]
tags: [schema, ids, sqlite, tcgdex]
created: 2026-05-23
updated: 2026-05-23
---

# Catalog — Schema & ID Systems

> Что в `data/cards.db`, какие IDs мы храним, как они мапятся.

DB schema canonical reference — [[../06-api/modules/db]]. Эта заметка — Catalog-side view: ID соглашения + external mappings.

## Core IDs

| ID | Format | Source | Purpose |
|----|--------|--------|---------|
| `tcgdex_id` | `<lang>-<set>-<number>` (e.g. `en-base1-25`) | [TCGdex](https://tcgdex.dev) | **Primary key.** Стабильный, language-aware, human-readable. |
| `cm_id_product` | numeric | CardMarket | CM product page ID для URL `https://www.cardmarket.com/en/Pokemon/Products/...?productID=N` |
| `tcgplayer_id` | numeric | TCGPlayer | US-market product ID |
| `pricecharting_url` | full URL | PriceCharting | Direct product page URL (fuzzy-matched) |
| `poketrace_id` | from PokeTrace API | PokeTrace Pro | Their internal card ID |

## Why `tcgdex_id` as primary

- **Stable**: TCGdex обновляется но IDs не меняются
- **Language explicit**: `en-base1-25` vs `jp-base1-25` — sister cards
- **Self-explaining**: легко debug, ничего не нужно lookup
- **Open data**: TCGdex API public, легко refresh

## External ID mapping table

`card_external_ids`:
```
tcgdex_id (FK) | system        | external_id        | confidence
en-base1-25    | tcgplayer     | 23456              | 1.0
en-base1-25    | poketrace     | abc-def-123        | 1.0
en-base1-25    | cardmarket    | 78901              | 0.95
jp-sm12-25     | poketrace     | xyz-456            | 1.0
```

Confidence < 1.0 = fuzzy-matched, может быть wrong. Future: human verification UI.

## Set IDs

- TCGdex set slug used directly (e.g. `base1`, `sm12`, `sv01`)
- Cross-language: same set может иметь разные set IDs across languages
- Example: "Base Set" EN = `base1`, but "拡張パック⓪" JP = `jp-promo-base-equivalent` (other slug)
- `sets.expansion_id` column tracks parent expansion

## Collector number format

- EN: `"25"`, `"25/102"`, `"SV-01"`, `"TG01"`, `"BW-29"`
- JP: `"025/090"`, `"AR-01"`, `"⑲"`
- TW: similar to JP, sometimes `"025/100"` or `"PROMO"`

Storage: `cards.collector_number` as string (raw form), `cards.collector_number_normalized` (lowercased, digits-extracted) для matching.

## Foiling / variant

`cards.foiling` enum-ish string: `normal`, `holo`, `reverse_holo`, `secret_rare`, `full_art`, etc. Sometimes encoded в TCGdex card variant suffix.

## Language values

- `en` — English (Pokemon TCG International)
- `jp` — Japanese (Pokemon Card Game, Japan)
- `tw` — Traditional Chinese (Taiwan / HK release)

См. [[language-coverage]] для breakdown.

## Why this matters for `/identify-v2`

5-level SQL lookup (см. [[../01-recognition/matching/5-level-sql-lookup]]) uses these fields для matching:
- Level 1: `set_id + collector_number`
- Level 2: `language + collector_number + total`
- Level 3: `language + name_normalized`
- Level 4: `name_normalized` (any lang)
- Level 5: CLIP fallback

Quality of catalog (correct `tcgdex_id`, populated `name_normalized`) directly impacts identification accuracy.

## Related

- DB schema: [[../06-api/modules/db]]
- Build catalog: [[../05-data-pipelines/scripts-catalog#Database Building (4)]]
- Language priorities: [[../../30-Resources/adr/2026-05-23-jp-over-tw-language-priority]]
