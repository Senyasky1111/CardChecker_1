---
type: adr
status: accepted
date: 2026-05-23
supersedes:
superseded-by:
area: [catalog, pricing]
tags: [adr, language, priority, japanese, taiwan]
---

# Japanese > Taiwanese > English priority for ambiguous card matches

## Context

Catalog включает три языковых версии большинства карт: **EN** (Pokemon TCG International), **JP** (Pokemon Card Game, Japan), **TW** (Traditional Chinese, Taiwan/HK release).

Часто карты с одинаковым artwork но разными set codes / numbering schemes. Когда OCR-результат matches несколько language variants (например, цифры читаются одинаково, имя не распознано), нужно tie-break.

Тот же вопрос для pricing lookup: external sources (CardMarket, PriceCharting) имеют разное coverage по языкам.

## Decision

**Tie-break priority: JP > TW > EN**.

При неоднозначном matching применяется в:
- Card identification result selection (если 2+ SQL matches с равным confidence)
- Pricing URL resolution (какую external page предпочесть)
- Catalog defaulting когда user не указал язык

## Alternatives considered

- **EN first** — default for English-language interface. **Reject**: коллекторская audience продукта — collector market for JP cards значительно больше TW/EN на сумме (по нашему пониманию запроса), и EN matches часто легко получить если они нужны.
- **By user locale** — auto-detect from device language. **Reject for now**: user может быть EN-speaker но коллекционировать JP карты (common). Добавит сложности без чёткого benefit.
- **No priority — return all matches** — UX-heavy: пользователю надо вручную выбирать каждый раз. **Reject**: для большинства карт top match всё ещё угадывается правильно при наличии priority.
- **TW > JP** — reversed. **Reject**: smaller collector base for TW market.

## Consequences

### Positive

- **Aligns with primary user base** — collector segment that drives engagement
- **Consistent** — одна и та же priority применяется везде в коде (SQL ordering, pricing fallback)
- **Simple** — three-tier static priority, easy to reason about

### Negative / risks

- **EN-primary users** (US market) могут получать JP variant when expecting EN. Mitigated tем что текстовый OCR обычно distinguishes (Kanji vs Latin).
- **Catalog bias** — если JP variant не существует, fallback на TW потом EN, но это просто означает что system "пытается JP first". Не блокер.
- **Future markets** (KR, ID, TH) не упоминаются. Если будем поддерживать → expand priority chain.

## Implementation

Priority применяется в:
- SQL `ORDER BY` clauses в `src/card_matcher.py` и `src/db.py` (lang-priority CASE expressions)
- Pricing source resolution в `src/cardmarket_url.py` и related modules
- См. недавний коммит `c924360` ("JP > TW priority in ALL code paths")

## Related

- [[../../20-Areas/04-catalog/_MOC]]
- [[../../20-Areas/01-recognition/matching/5-level-sql-lookup]]
- [[../../10-Projects/2026-Q2-jp-tw-ocr-accuracy]]
