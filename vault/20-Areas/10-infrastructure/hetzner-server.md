---
type: module
status: active
created: 2026-05-21
updated: 2026-05-21
area: [ops, infra]
tags: [hetzner, server, deployment]
related: [[deploy-procedure]], [[ssh-and-secrets]], [[docker-setup]]
---

# Hetzner Server

> **TL;DR**: Prod на Hetzner Cloud (Helsinki DC 2). Docker + Caddy + SQLite. Manual deploy через tar+scp+ssh.

## Сервер

| Поле | Значение |
|------|----------|
| **IP** | 89.167.31.124 |
| **DC** | Hetzner Cloud, Helsinki DC 2 |
| **OS** | Ubuntu 24.04 LTS |
| **App path** | `/opt/cardcheck/` |
| **Reverse proxy** | Caddy (port 80 → 8000) |
| **Memory limit (docker)** | 6 GB |

## Stack

- **Docker**: `python:3.11-slim` base, **1 uvicorn worker**
- **Caddy**: TLS termination + reverse proxy
- **SQLite WAL**: `data/cards.db` (~369 MB), mounted as Docker volume
- **Code path в контейнере**: `/app/`

## Что НЕ на сервере

- ❌ git репо — деплой через **rsync/scp + tar**, НЕ через git pull
- ❌ CI/CD — все деплои **manual**
- ❌ Rollback mechanism — будь осторожен что пушишь

## Что НА сервере уже

- ✅ `models/` (CLIP index, YOLO weights) — **не переуплоадятся** каждый деплой
- ✅ `data/cards.db` — обновляется только при price refresh
- ✅ `data/cardmarket/` — фото для recognition (не нужно для API, но удобно для дебага)

## SSH

```bash
ssh root@89.167.31.124
```

Ключ автоматически подтягивается из `~/.ssh/config`. См. [[ssh-and-secrets]].

## Domains

- `cardchecker.app` → веб-приложение (Base44)
- `bees.cardchecker.app` → FastAPI бэкенд (этот сервер)

## Health check

```bash
curl https://bees.cardchecker.app/health
```

## Deploy

См. [[deploy-procedure]].

⚠️ **CRITICAL**: см. [[deploy-safety-rules]] перед любым деплоем.

## Runbooks

- [[runbooks/redeploy]]
- [[runbooks/db-rebuild]]
- [[runbooks/server-recovery]]
- [[runbooks/log-investigation]]

## Связанные

- [[docker-setup]] — `Dockerfile` + `docker-compose.yml`
- [[deploy-procedure]] — пошаговая инструкция
- [[deploy-safety-rules]] ⚠️
- [[backups]]
