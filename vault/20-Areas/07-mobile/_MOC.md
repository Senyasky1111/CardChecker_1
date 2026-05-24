---
type: moc
status: active
created: 2026-05-21
updated: 2026-05-23
area: [mobile, frontend]
tags: [moc, react-native, expo]
---

# Mobile App MOC

> React Native 0.81.5 + Expo SDK 54, TypeScript strict.
> 6 Zustand stores с AsyncStorage persistence.

## Архитектура

- [[architecture]] — стек, навигация (Expo Router), структура папок
- [[api-client]] — backend integration layer

## Sweeping inventories

- [[screens-overview]] — 20 routes (Expo Router)
- [[components-overview]] — 38 components, grouped by domain
- [[hooks-overview]] — 6 hooks (React Query mutations + utilities)

## Stores (Zustand)

- [[stores/_MOC|stores MOC]] — index
- [[stores/auth-store]] — user + token
- [[stores/collection-store]] — saved cards, qty, conditions
- [[stores/scan-store]] — scan result + history
- [[stores/grading-store]] — grading session (photos, grade, defects)
- [[stores/settings-store]] — locale, theme, haptics, subscription
- [[stores/watchlist-store]] — price alerts
- [[stores/market-store]] — market data

## Roadmap

- [[missing-features]] — real auth, push, cloud sync, live prices

## Связанные

- API: [[../06-api/_MOC]]
- Webapp (sibling product): [[../08-webapp/_MOC]]
- Active project: [[../../10-Projects/2026-Q2-mobile-auth-and-cloud]]
