---
type: moc
status: active
created: 2026-05-21
updated: 2026-05-21
area: [backend, api]
tags: [moc, api, fastapi]
---

# API MOC

> FastAPI бэкенд. 20 endpoints в `src/api.py`.
> По одной ноте на каждый endpoint.

## Endpoints

### Identification

- [[endpoints/identify-v2]] — preferred ~100ms (OCR+SQL)
- [[endpoints/identify]] — legacy ~1s (CLIP)
- [[endpoints/detect-card]] — детекция + perspective correction
- [[endpoints/detect-number]] — OCR номера только
- [[endpoints/gemini-identify]] — Gemini Vision identification

### Card Info

- [[endpoints/card-{id}]] — детали карты + pricing
- [[endpoints/card-{id}-prices]] — multi-source pricing

### Grading

- [[endpoints/gemini-grade]] — AI condition grading (front + optional back)

## Config & Infra

- [[config-and-env]] — `.env`, API keys, `src/config.py`
- [[error-handling]]
- [[performance]] — latency budgets

## Roadmap

- [[auth-roadmap]] — добавление real auth
- [[rate-limiting]]

## Связанные

- Recognition: [[../01-recognition/_MOC]]
- Grading: [[../02-grading/_MOC]]
- Mobile client: [[../07-mobile/api-client]]
- Deployment: [[../10-infrastructure/_MOC]]
