---
type: project
status: planned
created: 2026-05-21
updated: 2026-05-21
priority: 2
target: 2026-Q2
area: [mobile, backend]
tags: [auth, cloud-sync, q2]
related: [[../20-Areas/07-mobile/missing-features]]
---

# Project: Mobile Auth + Cloud Sync

> **Priority #2**. Реальная авторизация и облачная синхронизация коллекции.

## Goal

Заменить локальное-only хранение на:
- Реальную авторизацию пользователей
- Облачную синхронизацию (Collection, Watchlist, Reports, Settings)
- Multi-device support

## Why

- Сейчас всё в AsyncStorage — терять при переустановке = плохо
- Конкуренты предлагают cloud sync — must-have для серьёзных коллекционеров
- Connects к monetization (Pro tier perks могут быть в облаке)

## Phases

### Phase 1: Auth backend
- [ ] Решить: Firebase Auth / Supabase Auth / своё через FastAPI?
- [ ] Если своё: JWT, refresh tokens, password reset flow
- [ ] Endpoints: `/auth/signup`, `/auth/login`, `/auth/refresh`, `/auth/me`

### Phase 2: User profile sync
- [ ] User entity на бэкенде
- [ ] Subscription tier persisted (Free/Plus/Pro)
- [ ] Connection с Stripe (см. [[../20-Areas/08-webapp/known-issues]] — там тоже нужен webhook)

### Phase 3: Collection / Watchlist sync
- [ ] Server-side schema (Postgres? Или продолжать SQLite?)
- [ ] Conflict resolution (last-write-wins?)
- [ ] Background sync с retry

### Phase 4: Mobile integration
- [ ] Auth screens (signup, login, forgot password)
- [ ] Sync indicator в UI
- [ ] Offline mode (queue mutations)

## Open questions

- **Auth provider**: build vs buy? Buy быстрее, но добавляет зависимость.
- **Database**: миграция с SQLite на Postgres сейчас или позже?
- **Webapp Base44**: имеет своих User'ов — как связать с mobile auth?

## Связанные

- Mobile features missing: [[../20-Areas/07-mobile/missing-features]]
- Webapp Stripe: [[../20-Areas/08-webapp/known-issues]]
- Monetization implementation: [[../20-Areas/11-product/monetization/implementation-order]]
