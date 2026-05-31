---
type: project
status: planned
created: 2026-05-24
updated: 2026-05-24
priority: 5
target: 2026-Q2
area: [mobile, recognition, catalog]
tags: [search, manual-input, q2, ux]
related: [[../20-Areas/04-catalog/_MOC]], [[../20-Areas/01-recognition/_MOC]]
---

# Project: Smart Manual Search (number / name / combo)

> **Priority #5** (new 2026-05-24). Альтернатива фото-сканированию: пользователь вводит номер ("096/080"), имя ("Pikachu"), или комбо — получает карту.

## Why

Photo scan не всегда удобен:
- Карта в sleeve / binder — глики, нет хорошего угла
- Слабое освещение
- Карта известна пользователю — зачем фоткать?
- Многие коллекционеры ведут digital list — копируют номера из таблиц
- Конкуренты (Ludex, CollX) имеют search, но он **тупой**: text-only, не понимает "096/080", не handles JP romanization, не понимает что "Pikachu V SWSH-049" ≠ "Pikachu V SWSH-049/SVE"

Это feature которая differentiates если сделать **умно**.

## What "smart" означает

### Number queries
Юзер вводит: `096/080`, `96/80`, `096`, `SV-01-096`, `SVE 096`.

Все эти варианты должны парситься в один логический query: `collector_number=096, total=080`.

Также нужен **set inference** — если только number без total, попытаться угадать set по контексту (recently scanned set? recently set in collection? popular sets с этим номером?).

Если ambiguous — показать ТОП-3 кандидата с set thumbnails, не assert "вот эта карта".

### Name queries
Юзер вводит: `Pikachu`, `pikachu V`, `pika`, `ピカチュウ`, `皮卡丘`.

Должно:
- Fuzzy match (опечатки)
- Multi-language — match across EN/JP/TW names
- Romaji input для JP names (`pikachu` → matches `ピカチュウ`)
- Variant disambiguation — Pikachu без других фильтров возвращает 200+ результатов, нужна categorization (by rarity? by year? by set series?)

### Combo (most powerful)
`Pikachu 25` → Pikachu, card number 25 (in any set с таким номером)
`Charizard ex 199/197` → Charizard ex, number 199/197 (specific match)
`Pikachu base set` → name + set
`Pikachu V holo` → name + variant

## Phases

### Phase 1: Backend search endpoint
- [ ] `/search?q=...` — accepts free-text query
- [ ] Query parser: detect numbers (`N` or `N/T`), set names, card names, language hints
- [ ] Multi-strategy SQL: try strictest matches first, expand if no results
- [ ] Response: ranked list of candidates с confidence + source ("matched by: number + name")
- [ ] Performance: < 50ms p95 для catalog of 49K cards
- [ ] Reuses existing 5-level SQL infrastructure where possible (см. [[../20-Areas/01-recognition/matching/5-level-sql-lookup]])

### Phase 2: Number-only and name-only specialized paths
- [ ] Number parser: handle EN/JP/TW conventions, alphabetic prefixes, fractional, full-set markers
- [ ] Name index: trigram or FTS5 (SQLite full-text search) для fast fuzzy
- [ ] Romaji ↔ kana converter: для JP romanization input
- [ ] Cross-language: input "Pikachu" returns JP/TW Pikachu cards too (depending user preference)

### Phase 3: Mobile UI
- [ ] New screen / mode toggle в `app/(tabs)/scan.tsx`: "Scan" / "Search"
- [ ] Search input с autocomplete
- [ ] Recent searches in `scan-store`
- [ ] Result list с card thumbnails + set badge
- [ ] Tap → existing card detail flow (`app/card/[id].tsx`)

### Phase 4: Webapp (parallel)
- [ ] Add search UI to Base44 webapp same way
- [ ] Shared backend → consistent results

### Phase 5: Smart suggestions / disambiguation
- [ ] If number-only and >1 result → "Which set?" picker с set art
- [ ] If name-only and >10 results → filter sidebar (set, rarity, year)
- [ ] "Last set you scanned" preference для autoinfer set context

## Done means

- User can find any card в catalog (49K cards) via text input alone в <3 taps
- Number-only queries: 100% accurate when number unique to set context, top-3 accurate when ambiguous
- Name queries: top-5 result includes target card в ≥95% cases (including JP/TW names)
- Latency: <100ms p95 end-to-end (mobile sends → backend → response → render)

## Risk

- **Catalog data quality** — relies on accurate `collector_number`, `name_normalized`, `eng_name`. Some JP/TW cards имеют incomplete fields (см. [[../20-Areas/04-catalog/language-coverage]]).
- **Romaji conversion** — Japanese has no 1:1 romaji rule (Hepburn vs Kunrei, modified spellings). Need pragmatic fallback.
- **Number ambiguity** — number `25` exists в hundreds of sets. Without set context, ambiguity high. UX must handle gracefully.

## Conflicting / related work

- 5-level SQL lookup [[../20-Areas/01-recognition/matching/5-level-sql-lookup]] already does name + number matching — we extend/reuse this same machinery, not duplicate it.
- Need to ensure JP > TW > EN priority still applies (см. [[../20-Areas/04-catalog/_MOC]]).
- text_index.py (already exists в src/) — see if reusable, or needs upgrade.

## Связанные

- Backend matching: [[../20-Areas/01-recognition/matching/5-level-sql-lookup]]
- Catalog metadata quality: [[../20-Areas/04-catalog/language-coverage]]
- Mobile scan screen: [[../20-Areas/07-mobile/screens-overview]]
- text_index module: [[../20-Areas/06-api/modules/text_index]]
