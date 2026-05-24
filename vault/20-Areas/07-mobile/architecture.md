---
type: module
status: active
created: 2026-05-21
updated: 2026-05-21
area: [mobile, frontend]
tags: [architecture, react-native, expo, zustand]
related: [[_MOC]], [[api-client]], [[persistence]]
source: mobile/
---

# Mobile Architecture

> **TL;DR**: React Native 0.81.5 + Expo SDK 54, TypeScript strict. File-based routing (Expo Router). 6 Zustand stores с AsyncStorage persistence. Tab navigator (Scan/Collection/Market/Profile) + modal screens.

## Stack

| Уровень | Что |
|---------|-----|
| **Framework** | React Native 0.81.5, React 19.1.0 |
| **Platform** | Expo 54.0.33 |
| **Language** | TypeScript 5.9.2 strict |
| **Routing** | Expo Router 6.0.23 (file-based) |
| **State** | Zustand 5.0.11 + persist middleware |
| **Storage** | AsyncStorage (key prefix `cardchecker-`) |
| **Server data** | TanStack React Query 5.90.21 |
| **UI** | Custom theme + Glass morphism (custom GlassCard component) |
| **Icons** | Lucide React Native, Expo Vector Icons |
| **i18n** | i18next + react-i18next, locales en/de/fr |
| **Camera** | expo-camera, expo-image-picker, expo-image-manipulator |
| **Animations** | react-native-reanimated 4.1.1, gesture-handler 2.30.0 |
| **Lists** | @shopify/flash-list 2.2.2 (virtualized) |

## Структура папок

```
mobile/
├── app/                          # Expo Router file-based screens
│   ├── (tabs)/                   # Tab navigator group
│   │   ├── _layout.tsx           # Tab bar config
│   │   ├── scan.tsx              # Scan tab
│   │   ├── collection.tsx        # Collection tab
│   │   ├── market.tsx            # Market tab
│   │   └── profile.tsx           # Profile tab
│   ├── auth/login.tsx            # Sign in (placeholder)
│   ├── card/[id].tsx             # Card detail
│   ├── scan/result.tsx           # Scan result modal
│   ├── grade/                    # Grading flow
│   │   ├── capture.tsx
│   │   ├── result.tsx
│   │   └── history.tsx
│   ├── collection/add.tsx
│   ├── market/alerts.tsx
│   ├── settings/{subscription,locale,hardware}.tsx
│   └── _layout.tsx               # Root layout (providers)
└── src/
    ├── api/                      # API client + endpoint wrappers
    ├── stores/                   # 6 Zustand stores
    ├── components/               # UI + domain components
    │   ├── ui/                   # Button, GlassCard, Badge, ...
    │   ├── cards/                # PokemonCard, PriceGrid
    │   ├── collection/, grading/, scan/, layout/
    ├── hooks/                    # useCamera, useIdentifyCard, useGradeCard, useSubscription, useHaptics
    ├── theme/                    # ThemeProvider, colors, typography, spacing, shadows, animations
    ├── i18n/                     # i18next + locales/{en,de,fr}.ts
    └── utils/                    # exportCollection, imageUtils, constants
```

## Navigation

**Tab Navigator** (4 main tabs):
- 📷 Scan — primary entry point
- 📚 Collection — saved cards
- 📈 Market — search + watchlist
- 👤 Profile — account, settings

**Modal screens** — scan result, grade result, subscription (slide-from-bottom)

**Stack screens** — card detail, settings, auth (slide-from-right)

Routing полностью file-based через Expo Router — folder structure = navigation tree.

## State Management

### Architecture principles

- **Stores minimal** — computed selectors живут в hooks или screens
- **Async ops в hooks** (`useIdentifyCard`, `useGradeCard`) — оборачивают API + store updates
- **Session vs persistent**:
  - Session state (текущий scan/grading) — **ephemeral**, не persisted
  - History + preferences — **persisted**

### 6 Stores (см. отдельные ноты)

| Store | File | Persisted | Что хранит |
|-------|------|-----------|-----------|
| [[stores/auth-store]] | `authStore.ts` | partial | Mock auth state |
| [[stores/collection-store]] | `collectionStore.ts` | full | Saved cards + UI state |
| [[stores/grading-store]] | `gradingStore.ts` | partial | History + preferences (session ephemeral) |
| [[stores/scan-store]] | `scanStore.ts` | partial | History only (session ephemeral) |
| [[stores/settings-store]] | `settingsStore.ts` | full | Theme, locale, tier, daily counts |
| [[stores/watchlist-store]] | `watchlistStore.ts` | full | Price watchlist + alerts |

## API Integration

См. [[api-client]] для деталей.

- Base URL: prod `https://api.cardchecker.app`, dev `http://localhost:8000` (или `10.0.2.2:8000` для Android emulator)
- Mock mode toggle: `EXPO_PUBLIC_USE_MOCK` env var
- Timeout handling: AbortController + setTimeout
- Functions: `identifyCardV2()`, `gradeCard()`, `getCardDetail()`, `getHealth()`

## i18n

- 3 locales: en (default), de, fr
- ~250 strings purchase коverage tabs, scan, collection, grading, market, profile, auth, subscription
- Sync с `settingsStore.locale` — useEffect в root `_layout.tsx`

См. [[i18n]] для деталей.

## Persistence

- AsyncStorage layer через Zustand `persist` middleware
- Keys prefixed `cardchecker-` (auth, collection, grading, scan, settings, watchlist)
- Partial persistence via `partialize` для session-vs-history separation

См. [[persistence]] для деталей.

## Missing Features

Confirmed missing (нужны для prod):

1. **Real authentication** — сейчас mock с 1-1.5s delay
2. **Live price polling** — watchlist `currentPrice` никогда не обновляется
3. **Push notifications** — alerts trigger локально, но не доставляются между сессиями
4. **Cloud sync** — данные только локально (теряются при reinstall)
5. **Subscription enforcement** — `TIER_LIMITS` defined но не actively checked

См. [[missing-features]] для подробного списка.

## Связанные

- API client: [[api-client]]
- Stores: [[stores/_MOC|All stores]]
- Persistence: [[persistence]]
- i18n: [[i18n]]
- Missing features: [[missing-features]]
- Project: [[../../10-Projects/2026-Q2-mobile-auth-and-cloud]]
