---
type: moc
status: active
created: 2026-05-21
updated: 2026-05-21
area: [ops, infra]
tags: [moc, deployment, docker, hetzner]
---

# Infrastructure MOC

> Прод-деплой, Docker, мониторинг, runbooks.

## Сервер

- [[hetzner-server]] — 89.167.31.124, `/opt/cardcheck/`
- [[ssh-and-secrets]] — где ключи, как НЕ закоммитить
- [[backups]]

## Docker

- [[docker-setup]] — `Dockerfile` + `docker-compose.yml`

## Деплой

- [[deploy-procedure]] — `deploy.sh`
- [[deploy-safety-rules]] ⚠️ CRITICAL — никогда не деплоить непротестированный код

## Runbooks

- [[runbooks/redeploy]]
- [[runbooks/db-rebuild]]
- [[runbooks/server-recovery]]
- [[runbooks/log-investigation]]

## Monitoring (roadmap)

- [[monitoring]] — если/когда добавим

## Связанные

- API: [[../06-api/_MOC]]
- Backups schedule: [[backups]]
