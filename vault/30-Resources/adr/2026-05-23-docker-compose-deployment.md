---
type: adr
status: accepted
date: 2026-05-23
supersedes:
superseded-by:
area: [infrastructure, deployment]
tags: [adr, docker, hetzner, deployment]
---

# Docker + docker-compose for Hetzner deployment

## Context

После того как backend стабилизировался, надо было поставить его на production-сервер (Hetzner cloud, single VM, Ubuntu). Solo dev, no SRE team, нужна reproducibility + минимум ops.

Backend = FastAPI + Tesseract + ONNX runtime + nginx reverse proxy + SQLite database.
Local dev: Windows + venv. Prod: Linux.

## Decision

**Docker + docker-compose**:
- Один `Dockerfile` для backend image (Python 3.11.9 + Tesseract + системные deps)
- `docker-compose.yml` orchestrates: backend service + nginx + volumes
- SQLite DB mounted as volume → персистится через restart, easy backup
- Models (`.onnx`, CLIP index) mounted as volumes тоже
- Deployment dir: `/opt/cardcheck/` на Hetzner

## Alternatives considered

- **systemd service + venv on host** — proще на старте. **Reject**: dependency drift между local/prod (особенно для Tesseract версий, OpenCV system libs), painful Python version pinning, env var management.
- **Bare-metal + Ansible** — overkill для solo dev на одной машине.
- **Kubernetes (k3s)** — overkill, добавляет 100× ops surface для one-server deployment.
- **Cloud Run / Lambda** — **reject**: cold-start неприемлемо для `/identify-v2` (~100ms budget), Tesseract/CLIP models больше типичных function size limits, нужны persistent volumes для SQLite.
- **Nixpacks / Railway / Render** — managed PaaS. **Reject**: дороже на нужный CPU/RAM (16GB Hetzner = €15/mo), меньше контроля над storage для 600+ GB images.

## Consequences

### Positive

- **Reproducible builds** — image тот же что локально (когда тестим production-like)
- **Easy rollback** — image tag previous + `docker compose up -d`
- **Volume persistence** для DB + models через container restarts
- **One-server simplicity** — `docker compose up -d` after `git pull`
- **Env separation** — `.env` файл на сервере, не в repo

### Negative / risks

- **Build time** ~3-5 min (Tesseract + Python deps install)
- **Docker overhead** на single-machine deployment ~5% RAM
- **Image size** ~2 GB (Tesseract + Python + ONNX runtime + CLIP weights)
- **Deploy safety** — нужны strict правила что НЕ переезжает в production (см. [[../../20-Areas/10-infrastructure/deploy-safety-rules]]). Без них легко улететь dev-only код в prod.

## Implementation

- `Dockerfile` — backend image
- `docker-compose.yml` — service definitions, volumes, networks
- `deploy.sh` — местная skripta для push + restart cycle
- `start_server.bat`, `setup_scheduler.bat` — Windows-side helpers
- Hetzner IP: 89.167.31.124, dir `/opt/cardcheck/`

## When to revisit

- Если переезжаем с одного VM на multi-server → k8s/swarm
- Если build time становится проблемой → multi-stage build optimization
- Если cold starts → swarm с health checks + warm replica

## Related

- [[../../20-Areas/10-infrastructure/deploy-procedure]]
- [[../../20-Areas/10-infrastructure/deploy-safety-rules]]
- [[../../20-Areas/10-infrastructure/_MOC]]
- [[../../_context-packs/deploying-to-prod]]
