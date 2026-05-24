---
type: note
status: stable
area: [mobile, frontend]
tags: [mobile, hooks, react-query]
created: 2026-05-23
updated: 2026-05-23
---

# Mobile Hooks Overview

> 6 кастомных hooks в `mobile/src/hooks/`. React Query mutations + утилитки.

| Hook | Purpose | Used in |
|------|---------|---------|
| `useIdentifyCard` | React Query mutation: compress image → POST `/identify-v2` → store result + haptics on success | scan flow |
| `useGradeCard` | React Query mutation: multi-photo upload → POST `/gemini/grade` → store, processing phases (uploading/analyzing/scoring) | grade/capture |
| `useCamera` | Permission management + capture helpers (takePhoto, pickFromGallery, quality config) | scan, grade/capture |
| `useCardDetails` | Fetch + cache single card details (likely reads collection store + API) | card/[id] |
| `useSubscription` | Check scan limits + feature gating per subscription tier | scan, paywall |
| `useHaptics` | Haptic feedback wrappers (success/error/select) | most interactions |

## Conventions

- **One file per hook**, named exactly `useX.ts`
- **TypeScript-first** — return type explicit
- **React Query** для server state, **Zustand** для client state (see [[stores/_MOC]])
- **Mock-aware** — when `EXPO_PUBLIC_USE_MOCK=true`, hooks return mock data via `mockData.ts`
- **No prop-drilling** — hooks consume stores directly when needed

## Related

- [[api-client]] — backend integration layer
- [[stores/_MOC]] — Zustand stores
- [[architecture]]
