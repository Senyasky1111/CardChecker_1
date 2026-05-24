---
type: module
status: active
source: mobile/src/stores/collectionStore.ts
storage-key: cardchecker-collection
persisted: full
created: 2026-05-21
updated: 2026-05-21
area: [mobile, state]
tags: [zustand, collection]
related: [[_MOC]], [[../architecture]]
---

# collectionStore

> **TL;DR**: Главный store пользовательской коллекции. Cards keyed by `tcgdex_id`, fully persisted, support sort/filter/view-mode.

## State

```typescript
{
  // Cards
  cards: Record<string, CollectionCard>  // keyed by tcgdex_id

  // UI state
  sortField: 'name' | 'price' | 'date' | 'set' | 'rarity'
  sortOrder: 'asc' | 'desc'
  filterSet: string | null              // by abbreviation
  filterRarity: string | null
  viewMode: 'grid' | 'list'
}
```

## CollectionCard shape

```typescript
{
  tcgdex_id, name, eng_name, set_name, abbreviation,
  collector_number, rarity, language, image_url,
  price_trend, price_foil_trend,        // EUR
  quantity, condition,                   // raw | near_mint | lightly_played | ...
  notes?: string,
  gradeResult?: GradeResult,             // attached after AI grading
  addedAt, updatedAt                     // timestamps
}
```

## Actions — Card CRUD

- `addCard(match: SQLCardMatch)` — создаёт или increment quantity
- `removeCard(tcgdexId)`
- `updateQuantity(tcgdexId, qty)` — удаляет если qty < 1
- `updateCondition(tcgdexId, condition)`
- `updateNotes(tcgdexId, notes)`
- `attachGrade(tcgdexId, gradeResult)` — связывает grading result с картой

## Actions — UI state

- `setSortField()`, `setSortOrder()`
- `setFilterSet()`, `setFilterRarity()`
- `setViewMode()`

## Computed (через get())

- `getCardCount()` → sum of quantities
- `getTotalValue()` → sum of (price_trend × quantity)
- `getSortedCards()` → filtered + sorted array
- `getCardsBySet()` → grouped by abbreviation
- `hasCard(tcgdexId)` → boolean

## Persistence

- Key: `cardchecker-collection`
- Fully persisted (без partialize)
- Survives app restart, app reinstall — **локально** (cloud sync TODO)

## Используется в

- `app/(tabs)/collection.tsx` — main display
- `app/scan/result.tsx` — "Add to Collection" button
- `app/card/[id].tsx` — card detail page
- `app/grade/result.tsx` — `attachGrade()` после grading
- `app/(tabs)/profile.tsx` — stats display

## Limits (по tier — см. [[../../11-product/monetization/tiers-free-plus-pro]])

| Tier | Limit |
|------|-------|
| Free | 1 binder, 100 cards |
| Plus | 5 binders, 1000 cards |
| Pro | Unlimited |

⚠️ Enforcement пока **не реализован** в runtime — `TIER_LIMITS` определён но не checked.

## Future work

- Cloud sync (см. [[../../../10-Projects/2026-Q2-mobile-auth-and-cloud]])
- Multi-binder support (UI-wise сейчас один)
- Conflict resolution для multi-device

## Связанные

- All stores: [[_MOC]]
- Mobile architecture: [[../architecture]]
- Add card flow: scan tab → scan result → addCard
