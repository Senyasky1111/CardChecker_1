---
type: module
status: roadmap
created: 2026-05-21
updated: 2026-05-21
area: [mobile, roadmap]
tags: [roadmap, missing-features]
related: [[architecture]], [[../../10-Projects/2026-Q2-mobile-auth-and-cloud]], [[../../10-Projects/2026-Q2-live-pricing]]
---

# Mobile — Missing Features

> **TL;DR**: Что в мобильном приложении ещё не сделано для prod readiness.

## 🔴 Critical (для prod launch)

### 1. Real Authentication

- **Сейчас**: Mock с 1-1.5s delay в [[stores/auth-store]]
- **Импакт**: Cloud sync невозможен → данные теряются при reinstall
- **Project**: [[../../10-Projects/2026-Q2-mobile-auth-and-cloud]]

### 2. Live Price Polling

- **Сейчас**: [[stores/watchlist-store]] хранит `currentPrice` но никогда не обновляет
- **Импакт**: Alerts никогда не срабатывают
- **Project**: [[../../10-Projects/2026-Q2-live-pricing]]

### 3. Push Notifications

- **Сейчас**: Триггеры считаются локально, нет mechanism доставки
- **Нужно**: `expo-notifications` setup + backend service
- **Связано с**: live pricing (без него нет alerts вообще)

### 4. Cloud Sync

- **Сейчас**: Collection, grading history, watchlist — только локально
- **Импакт**: Data loss при reinstall, нет multi-device
- **Нужно**: real auth → server-side API → conflict resolution

## 🟡 Important (для monetization)

### 5. Subscription Enforcement

- **Сейчас**: `TIER_LIMITS` defined в `api/types.ts` но НЕ checked at runtime
- **Импакт**: Free users могут exceed limits, нет conversion pressure
- **Что нужно**:
  - Server-side enforcement (single source of truth)
  - Daily reset server-side
  - UI блокировка с upgrade CTA
- **Связано с**: [[../../11-product/monetization/tiers-free-plus-pro]]

### 6. Stripe Subscription Flow

- **Сейчас**: `app/settings/subscription.tsx` — UI placeholder
- **Нужно**:
  - Stripe checkout integration (через [[../08-webapp/overview|webapp]] которая уже частично)
  - Webhook для tier update
  - In-app purchase для iOS / Google Play (mandatory для apps)

## 🟢 Nice-to-have

### 7. Hardware Pairing

- **Сейчас**: `app/settings/hardware.tsx` — placeholder
- **Идея**: Bluetooth scanner integration (для high-volume traders)

### 8. Better Image Handling

- **Сейчас**: Large card images НЕ resized
- **Импакт**: memory issues на low-end devices
- **Fix**: `expo-image-manipulator` уже imported но не активно используется

### 9. CSV/PDF Export

- **Сейчас**: `utils/exportCollection.ts` существует, CSV export частично
- **Что нужно**:
  - Pro-only feature gating ([[../../11-product/monetization/tiers-free-plus-pro]])
  - PDF export (jspdf + html2canvas — установлены в webapp но не mobile)

### 10. Analytics & Crash Reporting

- **Сейчас**: ничего
- **Нужно**: Sentry / Bugsnag для crashes, какая-то лёгкая analytics

### 11. Tests

- **Сейчас**: 0 tests
- **Нужно**: Component tests (React Native Testing Library), critical paths (scan flow, add to collection)

## ⚠️ Potential bugs

- **Collection filter logic**: dropdowns показывают все sets/rarities, даже если фильтр уже исключает all (UX issue)
- **Grade history timestamp**: `Date.now()` as ID может collide в rapid succession
- **Locale switching**: нет error boundary если translation keys missing
- **Memory on large collections**: FlashList помогает, но pagination на бэке нет — collection полностью в memory

## Priority order

1. **Real auth** ([[../../10-Projects/2026-Q2-mobile-auth-and-cloud]])
2. **Subscription enforcement** + Stripe (нужны для revenue)
3. **Live prices + push** ([[../../10-Projects/2026-Q2-live-pricing]])
4. **Cloud sync** (после auth)
5. Прочее по необходимости

## Связанные

- Mobile MOC: [[_MOC]]
- Architecture: [[architecture]]
- Active projects: [[../../10-Projects/_MOC]]
