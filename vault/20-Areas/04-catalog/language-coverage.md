---
type: note
status: stable
area: [catalog, languages]
tags: [language, coverage, en, jp, tw]
created: 2026-05-23
updated: 2026-05-23
---

# Catalog — Language Coverage

> EN/JP/TW breakdown: что покрыто, что нет, source per language.

## Volumes (approximate)

| Language | Cards | Source | Image coverage | CM URL | PC URL |
|----------|-------|--------|---------------|--------|--------|
| **EN** | ~22K | TCGdex (international) | ~99% | ~95% | ~95% |
| **JP** | ~15K | TCGdex JP + Pokemon-Card.com scrape | ~95% | ~60% | ~66% |
| **TW** | ~12K | TCGdex ZH-TW + asia.pokemon-card.com | ~85% | ~30% | ~62% |

Total: ~49K cards across 3 languages.

## Per-language pipeline

### EN
- Source: TCGdex API (`build_card_database.py`)
- Images: TCGdex HD images downloaded via `download_images_pokemontcg.py`
- Prices: CardMarket primary, TCGPlayer secondary
- Names: native EN, no translation needed

### JP
- Source: TCGdex JP + supplementary Pokemon-Card.com scrape via `scrape_pokemon_card_jp.py`
- Images: TCGdex JP + custom scrapes для missing sets
- Prices: PokeTrace (JP market focus), CardMarket JP listings
- Names: native JP (kanji + kana), `eng_name` field populated via `fill_eng_names_gemini.py` (Gemini translation)

### TW
- Source: TCGdex ZH-TW + asia.pokemon-card.com scrape via `scrape_pokemon_card_tw.py`
- Images: ZH-TW from TCGdex + custom scrapes
- Prices: thinner — PokeTrace partial coverage, CM TW limited
- Names: traditional Chinese, `eng_name` populated через cross-reference (`fill_cross_language.py`)

## Cross-language matching

Same artwork может exist в multiple languages с different set codes / numbers. Catalog tracks через:
- Common `pokedex_id` (Pokemon species, e.g. Pikachu = 25)
- `eng_name` field — anchor для cross-lang matching
- `set_link_table` — manual links для known equivalent sets

## Why JP > TW > EN priority

См. [[../../30-Resources/adr/2026-05-23-jp-over-tw-language-priority|ADR]]. TL;DR: JP collector base largest, tie-break лоутр TW > EN.

## Known gaps

- **Recent sets** — каждый new set требует import + scrape. Lag обычно 1-2 weeks.
- **Promotional cards** — many JP/TW promos missing from TCGdex, requires manual scrape.
- **Pre-2000 sets** — partial coverage для older Japanese sets (Vending Machine, etc.)
- **TW set IDs** — иногда unstable (TCGdex периодически renumbering).

## Future languages

Possible extension:
- KR (Korean) — Pokemon TCG Korea exists, smaller market
- DE/FR/IT/ES — European EN-equivalent sets (currently merged into EN)

Not roadmapped yet.

## Related

- [[schema-and-ids]]
- [[name-translations]]
- [[../../30-Resources/adr/2026-05-23-jp-over-tw-language-priority]]
- [[../../10-Projects/2026-Q2-jp-tw-ocr-accuracy]]
