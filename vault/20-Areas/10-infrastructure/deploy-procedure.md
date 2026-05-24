---
type: runbook
status: active
created: 2026-05-21
updated: 2026-05-21
area: [ops]
tags: [deploy, runbook]
related: [[hetzner-server]], [[deploy-safety-rules]]
---

# Deploy Procedure

> **TL;DR**: Manual deploy через tar+scp+ssh. Нет git pull на сервере.
> ⚠️ **Read [[deploy-safety-rules]] FIRST.**

## When to use

При любой нужде задеплоить **код** или **БД** в прод.

## ⚠️ Safety check (1 min) — DO THIS

- [ ] Я **протестировал** все изменения локально?
- [ ] Я знаю **точно какие файлы** меняются?
- [ ] Я делаю **incremental change** (1-2 файла), а не "deploy whole project"?
- [ ] У меня есть **revert plan** на случай если сломается?

Если хоть один ответ "нет" — **остановись и подумай**.

## Full code deploy (slower, with rebuild)

```bash
# 1. Create tarball (только нужные файлы)
tar czf /tmp/deploy.tar.gz \
  src/ scripts/ data/cards.db requirements.txt \
  Dockerfile docker-compose.yml .env static/

# 2. Upload
scp /tmp/deploy.tar.gz root@89.167.31.124:/tmp/

# 3. Extract + rebuild + restart
ssh root@89.167.31.124 "
  cd /opt/cardcheck && \
  tar xzf /tmp/deploy.tar.gz && \
  docker compose build && \
  docker compose up -d
"

# 4. Verify
curl https://bees.cardchecker.app/health
```

## DB-only update (fast, no rebuild)

Когда обновляются только цены / catalog metadata:

```bash
# 1. Upload DB
scp data/cards.db root@89.167.31.124:/opt/cardcheck/data/cards.db

# 2. Restart container (просто перечитать БД)
ssh root@89.167.31.124 "cd /opt/cardcheck && docker compose restart"

# 3. Verify
curl https://bees.cardchecker.app/health
```

## Single-file deploy (если правишь один скрипт/модуль)

```bash
# Например для src/api.py
scp src/api.py root@89.167.31.124:/opt/cardcheck/src/api.py

# Перезапустить uvicorn (docker compose restart переподнимет процесс)
ssh root@89.167.31.124 "cd /opt/cardcheck && docker compose restart"
```

## Verify

```bash
# Health
curl https://bees.cardchecker.app/health

# Логи (последние 100 строк)
ssh root@89.167.31.124 "cd /opt/cardcheck && docker compose logs --tail=100 -f"

# Smoke test endpoint
curl -X POST https://bees.cardchecker.app/identify-v2 \
  -F "image=@test_image.jpg"
```

## Что НЕ работает

- **`deploy.sh`** в репо — требует `hcloud` CLI (не установлен) и `rsync` (не на Windows). Не использовать.

## Past incidents

- 2026-05-13 — TAG CDN migration, не deploy-related, но напоминание следить за external sources

## Rollback

⚠️ Нет автоматического rollback. План на случай провала:
1. SSH на сервер
2. Восстановить файлы из backup (если есть)
3. Если backup нет — re-deploy предыдущей рабочей версии локально

## Связанные

- [[hetzner-server]]
- [[deploy-safety-rules]] ⚠️ MUST READ
- [[runbooks/server-recovery]]
- [[backups]]
