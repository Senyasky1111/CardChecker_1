---
type: note
status: stable
area: [business, monetization]
tags: [pricing, subscription, tiers]
created: 2026-05-23
updated: 2026-05-23
---

# Monetization

> Subscription model (free / standard / premium). Decision history в [[../../30-Resources/adr/2026-03-22-monetization-subscription-not-credits]].

## Model

**Subscription** (monthly/yearly), not credits.

Why: predictable revenue, simpler UX (no balance management), aligns with usage patterns (collectors scan many cards but rarely in pure burst).

Tiers (current — see `mobile/src/api/types.ts` `TIER_LIMITS`):

| Tier | Scans/day | Collection size | Alerts | Export | Grading |
|------|-----------|-----------------|--------|--------|---------|
| Free | limited | small | few | no | preview |
| Standard | higher | bigger | more | yes | full |
| Premium | unlimited | unlimited | unlimited | yes | full + priority |

Точные числа в коде — `TIER_LIMITS` в types.ts. Update этой заметки when changes (но source of truth — code).

## Pricing

Pricing experiments TBD. App Store / Play Store currently free-to-use с optional premium features (per [[store-listing|store description]]).

## Conversion funnel (planned)

```
install → onboarding → first scan → see paywall info → free tier usage → hit limit → upgrade
```

Critical paywall touchpoints:
- Scan limit hit
- Trying advanced grading features
- Trying to set 5+ alerts

## Future considerations

- **One-time grading credits** для casual users (don't want subscription)
- **Annual discount** standard
- **Team / pro plan** для shop owners

## Related

- [[../../30-Resources/adr/2026-03-22-monetization-subscription-not-credits]]
- [[store-listing]]
- [[../11-product/_MOC]]
- `mobile/src/api/types.ts` (TIER_LIMITS)
- `app/settings/subscription.tsx` (UI)
