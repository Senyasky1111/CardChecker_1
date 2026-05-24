---
type: note
status: stable
area: [mobile, frontend]
tags: [mobile, screens, routes, expo-router]
created: 2026-05-23
updated: 2026-05-23
---

# Mobile Screens Overview

> 20 routes в `mobile/app/`. Expo Router file-based routing. По одной строке на screen.

## Tabs (bottom navigation)

| Route | Purpose |
|-------|---------|
| `app/(tabs)/scan.tsx` | **Primary entry** — camera viewfinder + image upload (flash, scan button, gallery picker) |
| `app/(tabs)/collection.tsx` | Portfolio grid с sort (recent/price/rarity/name) + filter + search (FlashList 60fps) |
| `app/(tabs)/market.tsx` | Market alerts + price tracking |
| `app/(tabs)/profile.tsx` | User profile, collection stats, export |
| `app/(tabs)/_layout.tsx` | Bottom tab navigation layout |

## Auth

| Route | Purpose |
|-------|---------|
| `app/auth/login.tsx` | Authentication screen (placeholder — real auth pending [[../../10-Projects/2026-Q2-mobile-auth-and-cloud]]) |

## Card detail flow

| Route | Purpose |
|-------|---------|
| `app/card/[id].tsx` | Card detail: full info, quantity, condition grade, prices, delete/edit, share deeplink |
| `app/scan/result.tsx` | Card identification result from image scan |
| `app/collection/add.tsx` | Add card to collection workflow |

## Grading flow

| Route | Purpose |
|-------|---------|
| `app/grade/capture.tsx` | Multi-photo capture для grading (PhotoSlotGrid: front/back/holo/angle) |
| `app/grade/result.tsx` | Grading result display с defect heatmap |
| `app/grade/history.tsx` | Past grading results list |

## Market

| Route | Purpose |
|-------|---------|
| `app/market/alerts.tsx` | Price alert management (CRUD) |

## Settings

| Route | Purpose |
|-------|---------|
| `app/settings/hardware.tsx` | Camera / device settings (resolution, flash defaults) |
| `app/settings/locale.tsx` | Language preferences (en/de/fr) |
| `app/settings/subscription.tsx` | Subscription tier management |

## Misc

| Route | Purpose |
|-------|---------|
| `app/index.tsx` | Splash / home (redirects to tabs after init) |
| `app/_layout.tsx` | Root layout с theme provider, query client, store init |
| `app/+html.tsx` | Web/SSR support (Expo) |
| `app/+not-found.tsx` | 404 fallback |

## User flow (golden path)

```
splash → tabs/scan → (take photo) → scan/result
                                      ↓
                                 card/[id]
                                      ↓
                          collection/add → tabs/collection
                                      ↓
                              grade/capture → grade/result
                                                ↓
                                          grade/history
```

## Related

- [[architecture]] — overall RN+Expo architecture
- [[components-overview]] — UI building blocks
- [[stores/_MOC]] — state management
- [[api-client]] — backend integration
