---
type: module
status: active
source: src/db.py
lines: 228
related: [[../../04-catalog/_MOC]], [[../endpoints/card-by-tcgdex-id-prices]]
area: [backend, database]
tags: [module, sqlite, schema]
created: 2026-05-21
updated: 2026-05-21
---

# db.py

> **TL;DR**: SQLite schema + connection mgmt для card database. WAL mode для multi-process safety.

## Public surface

- `get_connection(db_path) → sqlite3.Connection` — WAL mode, row_factory, 30s timeout
- `init_db(conn)` — create tables + indexes
- `migrate_db(conn)` — apply schema migrations safely (idempotent)
- `ensure_schema(db_path) → sqlite3.Connection` — one-call init + migrate

## Tables

### Core

| Table | Purpose |
|-------|---------|
| `sets` | TCGdex sets (EN), pokemon-card.com (JP), asia.pokemon-card.com (TW) |
| `cards` | Multi-language card records: tcgdex_id, language, collector_number, name_normalized, cm_id_product, eng_name |

### Pricing

| Table | Purpose |
|-------|---------|
| `prices` | CardMarket snapshot: avg, low, trend, foil_trend |
| `prices_external` | PokeTrace + Pokemon-API daily snapshots (condition/country/currency) — **главная prices table** |
| `price_history` | Deep PokeTrace `/history` endpoint data (legacy, для long-term trends) |

### External IDs

| Table | Purpose |
|-------|---------|
| `card_external_ids` | PokeTrace, TCGPlayer, Pokemon-API mappings |

### Listings + state

| Table | Purpose |
|-------|---------|
| `ebay_sold_listings` | Phase 2: direct eBay URLs + sold prices |
| `enrichment_runs` | Track enrichment script progress для resumability |

## Indexes

- `(set_id, number)` — composite для number+set lookup
- `(language, number, total)` — для cross-language matching
- `(language, name_normalized)` — для fuzzy name search

## Connection settings

- **WAL mode** — Write-Ahead Logging, multi-process safe
- **30s busy timeout** — для concurrent writes (price refresh во время API requests)
- **Foreign keys enabled**
- `row_factory = sqlite3.Row` — dict-like row access

## Path

- `data/cards.db` — main DB (369 MB)
- `data/scraper.db` — отдельная DB для TAG scraper state ([[../../05-data-pipelines/tag-scraping/overview]])

## Migrations

- Idempotent — `can_fail=True` для duplicate column errors
- Migrations добавляют columns но не дропают (safe rollback)

## Phase 2 columns

В `prices_external` recent additions:
- `tcgplayer_id`, `top_price_eur`, `has_graded`, `enriched_at`
- Для multi-source enrichment workflow

## Связанные

- Catalog MOC: [[../../04-catalog/_MOC]]
- Pricing endpoint: [[../endpoints/card-by-tcgdex-id-prices]]
- Data pipelines: [[../../05-data-pipelines/_MOC]]
