---
type: moc
status: active
created: 2026-05-21
updated: 2026-05-21
area: [mobile, state]
tags: [moc, zustand, stores]
---

# Mobile Stores MOC

> 6 Zustand stores с AsyncStorage persistence. Key prefix `cardchecker-`.

## Stores

| Store | Persisted | Что хранит |
|-------|-----------|-----------|
| [[auth-store]] | partial | Mock auth (isAuthenticated, user, token) |
| [[collection-store]] | full | Saved cards (по tcgdex_id) + UI state |
| [[grading-store]] | partial | History + preferences (session ephemeral) |
| [[scan-store]] | partial | History only (session ephemeral) |
| [[settings-store]] | full | Theme, locale, tier, daily counts |
| [[watchlist-store]] | full | Price watchlist + alerts |

## Дизайн-принцип

- **Session state** (current scan, grading) — **не persisted**
- **History + preferences** — persisted
- **Computed selectors** в hooks/screens, не в store
- **Async ops** в hooks (`useIdentifyCard`, etc.), не напрямую в store

## Persistence через middleware

```typescript
import { persist, createJSONStorage } from 'zustand/middleware';
import AsyncStorage from '@react-native-async-storage/async-storage';

create<State>()(
  persist(
    (set, get) => ({ ... }),
    {
      name: 'cardchecker-storeName',
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (state) => ({ historyOnly: state.history }),  // partial если нужно
    }
  )
);
```

## Связанные

- Mobile MOC: [[../_MOC]]
- Architecture: [[../architecture]]
- Persistence detail: [[../persistence]]
