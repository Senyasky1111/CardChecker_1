---
type: adr
status: accepted
date: 2026-05-23
supersedes:
superseded-by:
area: [pricing, data-pipelines]
tags: [adr, pricecharting, fuzzy-match, thresholds, heuristic]
---

# PriceCharting fuzzy match: 95% / 66% / 62% three-tier thresholds

## Context

PriceCharting URLs не имеют API — resolved через **fuzzy string match** card name + set name + variant против their HTML listings. Coverage uneven по языкам: ~95% для EN, ~66% для JP, ~62% для TW (см. cardlist в [[../../20-Areas/03-pricing/sources/pricecharting]]).

Single threshold не работает — too strict теряет JP/TW matches, too lenient даёт false positives (CardCharting page для wrong variant).

## Decision

**Three-tier thresholds** по языку:
- **EN: 95%** — strict, потому что coverage высокий и false positives дороги
- **JP: 66%** — relaxed, чтобы покрыть imperfect transliterations и romaji vs kana spellings
- **TW: 62%** — самый lenient, narrow coverage означает что если что-то matches вообще — скорее всего правильно

Алгоритм: try strict cutoff first; если no match → drop to next tier; если still none → no PriceCharting URL.

## Rationale (post-hoc, не строго обоснованно)

Эти числа подобраны эмпирически:
- **95%** для EN — на тестовом наборе 100 карт false positive rate <1% при coverage >95%
- **66% / 62%** для JP/TW — derived от наблюдений где **real positives** falling below 95% but still semantically right (different romanization, missing diacritics)
- Точная формула / paper не использовалась — это calibrated thresholds, не статистически выведённые

**Honest note**: не задокументирован formal calibration process. Если эти thresholds окажутся wrong в production — пересмотреть с proper precision/recall measurement.

## Alternatives considered

- **Single threshold (say 70%)** — компромисс, но даёт false positives для EN и недопокрывает JP/TW.
- **ML-based matching** (embedding similarity на names) — overkill для table-lookup задачи, добавляет infra.
- **Manual mapping table** — captures known mappings, но не scaleable для 50K cards × 3 langs.
- **Use rapidfuzz token-set scorer** vs current scorer — possibly better but требует proper benchmark first.

## Consequences

### Positive

- **Coverage tradeoff explicit** — language-aware thresholds match observed coverage distribution
- **Tiered fallback** — strict сначала, relaxed потом → minimizes false positives where possible
- **Simple to implement** — pure stdlib + rapidfuzz

### Negative / risks

- **Thresholds are heuristic** — no formal precision/recall numbers stored
- **Drift over time** — if PriceCharting changes their naming conventions, thresholds need retuning
- **Coverage gap** — карты которые fail at 62% получают no PriceCharting URL, no price. ~38% TW cards.

## Implementation

- `src/cardmarket_url.py` and PriceCharting URL resolution code (`scripts/resolve_pricecharting_urls.py`, `scripts/scrape_pc_sets.py`)
- Recent expand: коммит `5665af4` ("expand PriceCharting URL coverage for JP/TW cards") — adjusted thresholds and scraping strategy

## When to revisit

- Если false positive rate в production > 5% (user reports wrong card price)
- Если ML embeddings становятся cheap enough → switch to semantic similarity
- Если PriceCharting запускает официальный API → drop fuzzy match entirely

## Related

- [[../../20-Areas/03-pricing/sources/pricecharting]]
- [[../../20-Areas/06-api/modules/cardmarket_url]]
