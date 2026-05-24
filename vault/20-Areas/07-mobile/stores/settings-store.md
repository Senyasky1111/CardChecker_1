---
type: module
status: active
source: mobile/src/stores/settingsStore.ts
storage-key: cardchecker-settings
persisted: full
created: 2026-05-21
updated: 2026-05-21
area: [mobile, state]
tags: [zustand, settings]
related: [[_MOC]], [[../i18n]]
---

# settingsStore

> **TL;DR**: App preferences — theme, locale, currency, subscription tier, daily usage counters.

## State

```typescript
{
  // UI preferences
  themeMode: 'light' | 'dark' | 'system',
  hapticEnabled: boolean,           // default true

  // Locale
  locale: string,                   // 'en', 'de', 'fr'
  currency: string,                 // 'EUR', 'USD', etc.

  // Subscription
  tier: 'free' | 'standard' | 'premium',

  // Usage tracking (per day)
  dailyScanCount: number,
  dailyGradeCount: number,
  lastUsageDate: string             // ISO date для rollover
}
```

## Actions

- `setThemeMode(mode)`
- `setHapticEnabled(bool)`
- `setLocale(locale)` — syncs с i18next через useEffect в `_layout.tsx`
- `setCurrency(currency)`
- `setTier(tier)`
- `incrementScanCount()` — increment + auto-reset если date changed
- `incrementGradeCount()` — increment + auto-reset если date changed
- `resetDailyCountsIfNeeded()` — checks date rollover

## Persistence

- Key: `cardchecker-settings`
- Fully persisted

## Daily counter logic

```typescript
incrementScanCount() {
  resetDailyCountsIfNeeded();  // если новый день - reset
  set({ dailyScanCount: dailyScanCount + 1 });
}
```

Каждый call к API проверяет date — если не today, ресетит счётчики.

## Tier mapping (см. [[../../11-product/monetization/tiers-free-plus-pro]])

Mobile-side tier names:
- `'free'` — Free tier
- `'standard'` — Plus tier ($6.99/mo)
- `'premium'` — Pro tier ($14.99/mo)

Хм, naming не совпадает с webapp/backend tier names. ⚠️ TODO: унифицировать.

## Используется в

- `app/_layout.tsx` — theme + i18n sync
- `app/(tabs)/profile.tsx` — theme picker, tier display, settings list
- `app/settings/locale.tsx` — language picker
- `app/settings/subscription.tsx` — subscription comparison
- `hooks/useSubscription.ts` — tier checks
- Везде где нужны usage limits

## ⚠️ Limit enforcement

`TIER_LIMITS` defined в `api/types.ts` но НЕ актively gated:
- Free user может превысить 30 scans/week без блока
- Должно проверяться при scan/grade action

См. [[missing-features]] (будет создан).

## Связанные

- All stores: [[_MOC]]
- Subscription page: `app/settings/subscription.tsx`
- Monetization decisions: [[../../11-product/monetization/tiers-free-plus-pro]]
- i18n: [[../i18n]]
