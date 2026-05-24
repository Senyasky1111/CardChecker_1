---
type: adr
status: accepted
date: 2026-02-15
supersedes:
superseded-by:
area: [backend, database]
tags: [adr, database, sqlite]
---

# Use SQLite (WAL mode), not Postgres

## Context

В начале проекта (early 2026) нужно было выбрать БД для:
- 50K+ cards metadata
- Daily price snapshots
- Multi-language (EN/JP/TW)
- External ID mappings (CardMarket, TCGPlayer, PriceCharting, PokeTrace)

Конфигурация: solo dev, single backend server (Hetzner), один uvicorn worker.

## Decision

**SQLite в WAL mode**, mounted as Docker volume в production.

## Alternatives considered

- **Postgres** — production-grade, multi-writer, full SQL features. **Reject**: overkill для текущих требований, добавляет ops surface (backup, monitoring, версии).
- **MongoDB** — schemaless хорошо для evolving card metadata. **Reject**: нужны joins для prices/external IDs, schema всё равно стабилизировался.
- **DuckDB** — fast analytics. **Reject**: не дизайнили для transactional writes (нужно для daily price updates).

## Consequences

### Positive

- **Zero ops**: один файл, backup = scp
- **Embedded** — без отдельного процесса, проще Docker compose
- **WAL mode** allows concurrent reads while writes happen (good для daily price refresh во время API serving)
- **Fast**: queries <5ms даже при 50K cards
- **Easy to ship**: `data/cards.db` 369MB legko sync'ится с локалки на сервер через `scp` ([[../../20-Areas/10-infrastructure/deploy-procedure#db-only-update]])
- Backup = "файл с timestamp"

### Negative / risks

- **Single-writer constraint** — если когда-то понадобится horizontal scaling backend, придётся мигрировать
- **No advanced indexes** (GIN, GIST, full-text properly) — full-text search via LIKE
- **Lock contention possible** при долгих writes — пока не наблюдалось
- **NO replication / HA** — single point of failure (mitigated daily backups)

## Implementation

- `src/db.py` — schema + `get_connection()` с WAL mode + 30s timeout
- Path: `data/cards.db`
- Migrations: idempotent в `migrate_db()`
- Foreign keys enabled

## When to revisit

Если/когда:
- Backend становится multi-server
- Concurrent writers > 1
- Нужны advanced full-text search (TS vectors)
- Daily refresh start blocking API (latency spikes)

Тогда — migrate to Postgres (estimated ~1 week работы с current schema).

## Related

- DB module: [[../../20-Areas/06-api/modules/db]]
- Deploy procedure: [[../../20-Areas/10-infrastructure/deploy-procedure]]
- Data pipelines: [[../../20-Areas/05-data-pipelines/_MOC]]
