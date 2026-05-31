---
type: project
status: in-progress
created: 2026-05-21
updated: 2026-05-24
priority: 1
target: 2026-Q2
area: [mobile, backend]
tags: [auth, cloud-sync, q2]
related: [[../20-Areas/07-mobile/missing-features]]
---

# Project: Mobile Auth + Cloud Sync

> **Priority #1** (promoted 2026-05-24 — tech debt block). Реальная авторизация и облачная синхронизация коллекции.

## Open decision (blocker for kickoff)

**Auth provider**: Firebase Auth / Supabase Auth / own (FastAPI + JWT)?

Trade-offs:
- **Firebase Auth**: fastest to ship, free tier generous (50K MAU), Google ecosystem, but vendor lock-in + privacy concerns + need separate backend integration anyway.
- **Supabase Auth**: open-source equivalent, Postgres-native, generous free tier, less mature than Firebase, mate с self-hosted option later.
- **Own (JWT + FastAPI)**: full control, no vendor, but ~2 weeks of careful work (password reset flow, email verify, refresh token rotation, rate limiting against brute force).

Recommendation pending. See "Decision needed" section below.

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

- **Auth provider**: see "Open decision" at top. **Action**: pick one before Phase 1.
- **Database**: SQLite остаётся для card catalog; user data может жить в auth provider's DB (Supabase Postgres) или separate Postgres. Не нужно мигрировать catalog.
- **Webapp Base44**: имеет своих User'ов — как связать с mobile auth? Если Supabase — single source of truth для both. Если Firebase — нужен mapping layer. Если own — webapp нужно мигрировать.

## Decision needed (before any code)

Pick auth provider. Default recommendation if unsure: **Supabase** (best balance — open-source, Postgres, generous free, escape hatch to self-host).

## Связанные

- Mobile features missing: [[../20-Areas/07-mobile/missing-features]]
- Webapp Stripe: [[../20-Areas/08-webapp/known-issues]]
- Monetization implementation: [[../20-Areas/11-product/monetization/implementation-order]]
