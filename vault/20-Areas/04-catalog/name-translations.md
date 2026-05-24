---
type: note
status: stable
area: [catalog, languages]
tags: [translation, names, gemini]
created: 2026-05-23
updated: 2026-05-23
---

# Catalog — Name Translations

> Как мы получаем EN equivalent для JP/TW cards.

## Why

User-facing наименование часто требует EN name (универсальное). JP/TW cards имеют native names — нужен mapping.

Use cases:
- Display EN name alongside native в card detail
- Search by EN name finds JP/TW variants
- External pricing lookups (PriceCharting, TCGPlayer) primarily EN-keyed

## Sources

### 1. TCGdex native fields
Часть TCGdex cards уже имеют `name.en` populated в их API. Used as primary source когда available.

### 2. Pokemon name dictionary
`pokemon_name_dict.json` — fixed mapping Pokemon species names (Pikachu = ピカチュウ = 皮卡丘). Stable, well-known, manually curated.

Applied via `scripts/self_fill_eng_name.py` (regex-pattern based) для simple cases like "ピカチュウ" → "Pikachu".

### 3. Cross-language cross-reference
`scripts/fill_cross_language.py` (~439 строк): match cards across languages by:
- Same pokedex_id
- Same set equivalent
- Same collector number / position
→ inherit EN name from matched EN card

Works well для Pokemon (species names map cleanly).

### 4. Gemini translation (Trainer/Supporter names)
Trainer / Supporter / Item cards имеют unique localized names which don't map mechanically. Example:
- JP: "ボスの指令" 
- EN: "Boss's Orders"

Не выводится automatically — нужна semantic translation.

`scripts/fill_eng_names_gemini.py` (~320 строк):
- Batch unprocessed JP/TW Trainer/Supporter cards
- Calls Gemini API with context (card text, type, set)
- Returns proposed EN name
- Cross-references против Pokemon TCG International card list для validation
- Writes `cards.eng_name` if confidence high

Gemini occasionally hallucinates — ~5% need manual review. Tracking flag `eng_name_source` distinguishes ('tcgdex', 'dict', 'cross-ref', 'gemini', 'manual').

## Translation files

- `pokemon_name_dict.json` — Pokemon species names (manual)
- `eng_name_translations.json` — cached Gemini outputs (avoid re-calling API)

## Future work

- Manual review UI для borderline Gemini translations
- Expand dictionary с new species (each generation добавляет ~80)
- Possibly fine-tune small LLM на verified translations для cost reduction

## Related

- [[schema-and-ids]] — where `eng_name` lives
- [[language-coverage]] — coverage per source
- Scripts: [[../05-data-pipelines/scripts-catalog#Name & Language Processing (3)]]
