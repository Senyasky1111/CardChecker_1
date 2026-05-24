---
type: module
status: active
source: mobile/src/stores/watchlistStore.ts
storage-key: cardchecker-watchlist
persisted: full
created: 2026-05-21
updated: 2026-05-21
area: [mobile, state]
tags: [zustand, watchlist, alerts]
related: [[_MOC]], [[../screens/market-watchlist]]
---

# watchlistStore

> **TL;DR**: Price watchlist (max 50 cards) + price alerts. **Polling сейчас не работает** — currentPrice никогда не обновляется автоматически.

## State

```typescript
{
  items: WatchlistItem[]  // max 50
}

type WatchlistItem = {
  id, tcgdex_id, name, eng_name, set_name, abbreviation, image_url,
  priceAtAdd: number,          // baseline
  currentPrice: number,        // latest known price
  targetPrice: number | null,  // null = watch-only
  alertDirection: 'above' | 'below',
  triggered: boolean,
  addedAt, lastUpdated
}
```

## Actions

- `addToWatchlist(card)` — игнорирует если уже watching
- `removeFromWatchlist(id)`
- `updateTargetPrice(id, target, direction)` — resets triggered to false
- `updateCurrentPrice(tcgdexId, price)` — **auto-triggers alert** если threshold met
- `markTriggered()`, `clearTriggered()`
- `clearAll()`

## Computed

- `isWatching(tcgdexId)` → boolean
- `getTriggeredAlerts()` → array с triggered=true

## Persistence

- Key: `cardchecker-watchlist`
- Fully persisted

## ⚠️ Missing functionality

### Live polling **не реализован**

`updateCurrentPrice()` существует как функция, но:
- Никто её не вызывает на background (нет polling job)
- `currentPrice` сохраняется как `priceAtAdd` всегда
- → **Alerts никогда не срабатывают**

Нужно для prod ready:
1. Background task что pollит prices (`/card/{tcgdex_id}/prices`)
2. Periodic update `currentPrice` для каждого watchlist item
3. Trigger notification если price crossed threshold

См. [[../../../10-Projects/2026-Q2-live-pricing]] — это main project для этого.

### Push notifications **не интегрированы**

Даже если `triggered = true` flag выставится, нет mechanism доставить notification пользователю:
- Нет `expo-notifications` setup
- Нет backend service для alerts когда app закрыто

## Limits (per tier)

| Tier | Watchlist size |
|------|---------------|
| Free | 5 cards |
| Plus | 25 cards |
| Pro | Unlimited |

⚠️ В коде hardcoded max 50 для UI safety, не tier-based limits enforcement.

## Используется в

- `app/(tabs)/market.tsx` — list display
- `app/card/[id].tsx` — Add to Watchlist button
- `app/market/alerts.tsx` — manage alerts

## Связанные

- All stores: [[_MOC]]
- Market screen: [[../screens/market-watchlist]]
- Live pricing project: [[../../../10-Projects/2026-Q2-live-pricing]]
- Webapp same issue: [[../../08-webapp/known-issues#8-watchlist-без-polling]]
