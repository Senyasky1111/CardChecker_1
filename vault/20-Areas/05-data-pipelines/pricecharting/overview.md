---
type: note
status: stable
area: [data-pipelines, pricecharting]
tags: [pricecharting, scraping, pricing]
created: 2026-05-23
updated: 2026-05-23
---

# PriceCharting Pipeline Overview

> PriceCharting URLs не имеют API — построены через fuzzy match against scraped HTML.

## Goal

PriceCharting — secondary US-market pricing source с broader JP/TW coverage than CardMarket. Нам нужны: product URLs (для "view on PC" link).

Note: prices напрямую не берём, только URL для user redirect (PC monetizes through their own page views).

## Pipeline stages

```
1. scrape_pc_sets.py              → discover set slugs via category pages
2. build_pricecharting_map.py     → comprehensive slug → set_id mapping
3. fetch_urls_cdp.py              → headless Chrome для tough pages (CDP protocol)
4. resolve_pricecharting_urls.py  → resolve slugs to final URLs, dedup
5. _fix_pc_urls.py                → JP/TW URL fixes (abbreviation removal)
6. _auto_map_pc.py                → auto-map remaining set_ids with validation
```

См. [[../scripts-catalog#PriceCharting (5)|scripts-catalog]].

## Fuzzy match thresholds

**95% EN / 66% JP / 62% TW** — three-tier thresholds. Полностью задокументировано в [[../../30-Resources/adr/2026-05-23-pricecharting-fuzzy-match-thresholds|ADR]].

## Outputs

- `cards.pricecharting_url` populated
- `cards.pricecharting_slug` (intermediate)
- Logs: matched / unmatched counts per language

## Failure modes

- **Page structure changes** — PC redesigns. `_fix_pc_urls.py` handles known patterns; new patterns require manual patch.
- **CDP failures** — headless Chrome instability в Docker. Сейчас CDP-fetching не в проде, только locally для bulk fills.
- **Slug ambiguity** — multiple slug variants для same set (e.g. "scarlet-violet" vs "scarlet-and-violet"). `build_pricecharting_map.py` deduplicates.

## Coverage

- EN: ~95%
- JP: ~66%
- TW: ~62%

Recent коммит `5665af4` ("expand PriceCharting URL coverage for JP/TW cards") — improvements в JP/TW.

## Related

- [[../../03-pricing/sources/pricecharting]]
- [[../../30-Resources/adr/2026-05-23-pricecharting-fuzzy-match-thresholds]]
- [[../scripts-catalog]]
