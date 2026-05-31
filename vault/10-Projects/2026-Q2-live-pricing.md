---
type: project
status: planned
created: 2026-05-21
updated: 2026-05-21
priority: 4
target: 2026-Q2
area: [pricing, backend]
tags: [pricing, live-updates, q2]
updated: 2026-05-24
related: [[../20-Areas/03-pricing/live-pricing-plan]]
---

# Project: Live Pricing (vs Daily Snapshots)

> **Priority #4**. Перейти с daily price snapshots на real-time price updates.

## Goal

Цены обновляются:
- Когда пользователь смотрит карту → real-time fetch (с кешем 1-24h)
- Background polling для watchlist items
- Push notifications если цена пересекла target

## Why

- Сейчас: 1 snapshot/день → данные могут быть протухшими на 24h
- Конкуренты дают live прайсы → ожидание рынка
- **Monetization tie-in**: live + alerts может быть Pro-only фичей

## Trade-offs

### Pros
- Свежее данные → больше доверия пользователей
- Watchlist alerts становятся реальной фичей
- Дифференциация от static price aggregators

### Cons
- Rate limits на источниках (CardMarket особенно)
- Cost — больше API calls = больше денег
- Кеширование становится сложнее
- Может потребоваться background worker (Redis + Celery? или async tasks?)

## Phases

### Phase 1: On-demand fetch
- [ ] `/card/{id}/prices?fresh=true` — fetch live (с rate limiting)
- [ ] Кеш 24h по умолчанию, `fresh=true` пропускает кеш
- [ ] Источник приоритета: CardMarket > PriceCharting > PokeTrace

### Phase 2: Watchlist polling
- [ ] Background job: для каждой `WatchItem` обновлять `current_price` 1-2 раза/день
- [ ] Если есть alert + target_price пересечён → notification
- [ ] Webapp [[../20-Areas/08-webapp/known-issues]] упоминает что polling сейчас не работает

### Phase 3: Push notifications
- [ ] Mobile: Expo Push Notifications setup
- [ ] Webapp: email/in-app notifications
- [ ] Тестировать UX (не спамить)

### Phase 4: Pro feature gating
- [ ] Live prices = Pro-only (см. [[../20-Areas/11-product/monetization/tiers-free-plus-pro]])
- [ ] Free → daily snapshots (как сейчас)
- [ ] Plus → 30-day history
- [ ] Pro → unlimited history + alerts

## Связанные

- Pricing MOC: [[../20-Areas/03-pricing/_MOC]]
- Live pricing plan: [[../20-Areas/03-pricing/live-pricing-plan]]
- Watchlist issue: [[../20-Areas/08-webapp/known-issues#8-watchlist-без-polling]]
- Monetization tie: [[../20-Areas/11-product/monetization/tiers-free-plus-pro]]
