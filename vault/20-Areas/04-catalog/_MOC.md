---
type: moc
status: active
created: 2026-05-21
updated: 2026-05-23
area: [catalog, backend]
tags: [moc, metadata, tcgdex]
---

# Catalog MOC

> Метаданные карт: schema, IDs, languages, translations.
> Источник правды: TCGdex (EN 22K + JP 15K + TW 12K = ~49K карт).

## Core

- [[schema-and-ids]] — DB schema overview + ID systems (tcgdex_id, CM, TCGPlayer, PC, PokeTrace mappings)
- [[language-coverage]] — EN/JP/TW breakdown, volumes, sources
- [[name-translations]] — как получаем EN names для JP/TW

## Related notes

- Module: [[../06-api/modules/db]] — canonical schema reference
- Pricing layer: [[../03-pricing/_MOC]]
- Build pipelines: [[../05-data-pipelines/_MOC]]

## ADRs in this area

- [[../../30-Resources/adr/2026-02-15-sqlite-not-postgres]]
- [[../../30-Resources/adr/2026-05-23-jp-over-tw-language-priority]]
