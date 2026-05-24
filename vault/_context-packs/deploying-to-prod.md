---
type: context-pack
status: active
created: 2026-05-21
updated: 2026-05-21
tags: [context-pack, deploy, critical]
---

# Context Pack: Deploying to Prod

> ⚠️ **Use BEFORE any prod deploy.** Никогда не пропускай эту проверку.

## SAFETY RULES (READ FIRST)

![[../20-Areas/10-infrastructure/deploy-safety-rules]]

## Deploy procedure

![[../20-Areas/10-infrastructure/deploy-procedure]]

## Server context

![[../20-Areas/10-infrastructure/hetzner-server]]

## Past incidents

См. секцию "Past mistakes" в [[../20-Areas/10-infrastructure/deploy-safety-rules]].

## Quick decision tree

**Что меняешь?**

- **Только цены / catalog** → DB-only deploy (`scp cards.db && docker compose restart`)
- **Один скрипт/модуль** → Single-file deploy (`scp src/X.py && restart`)
- **Несколько файлов или Dockerfile** → Full tar deploy + rebuild
- **Не уверен** → ОСТАНОВИСЬ, обсуди прежде чем пушить

## After deploy — verify

```bash
# 1. Health
curl https://bees.cardchecker.app/health

# 2. Реальный endpoint
curl -X POST https://bees.cardchecker.app/identify-v2 -F "image=@test_image.jpg"

# 3. Логи без новых ошибок
ssh root@89.167.31.124 "cd /opt/cardcheck && docker compose logs --tail=100"
```

Если хоть что-то не ОК → откатись локально и подумай.
