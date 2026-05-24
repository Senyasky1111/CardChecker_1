---
type: adr
status: accepted
date: 2026-03-22
supersedes:
superseded-by:
area: [product, monetization]
tags: [adr, monetization, subscription, pricing]
---

# Pure subscription model (Free/Plus/Pro), not credits

## Context

В начале webapp Base44 был **credit system** — пользователь покупает кредиты, тратит их на features (1 credit = 1 detailed report и т.д.). К Q1 2026 стало очевидно что эта модель не работает:

- **Friction**: User думает каждый раз "стоит ли это 1 credit?" — снижает usage
- **Conversion** низкий — purchase credits = большой commitment
- **Engineering complexity**: weird balance tracking, refunds, edge cases
- **Mobile platforms** не любят non-subscription IAP без consumable framework

Конкуренты (Ludex, CollX) — на subscription. Industry standard.

## Decision

**Полностью переход на subscription**. Три tier'а:

| Tier | Price | Annual (~28% off) |
|------|-------|-------------------|
| **Free** | $0 | — |
| **Plus** | $6.99/mo | $59.99/yr |
| **Pro** | $14.99/mo | $129.99/yr |

Кредиты **удалены** из новой модели. Имеющиеся пользователи с кредитами — будут migrated.

Структура limits — см. [[../../20-Areas/11-product/monetization/tiers-free-plus-pro]].

## Alternatives considered

- **Pay-per-use** (без подписки)
  - **Reject**: friction, low conversion, не масштабируется
- **Single subscription** (одна цена)
  - **Reject**: не captures different willingness-to-pay; Pro users готовы платить больше за power features
- **Freemium** только (без paid tiers)
  - **Reject**: нет revenue model
- **Hybrid (subscription + credits)**
  - **Reject**: complexity, confusing UX

## Consequences

### Positive

- **Predictable revenue** (MRR vs one-off purchases)
- **Less friction**: пользователь платит раз, использует без размышлений
- **Industry standard** — пользователи понимают модель
- **Clearer marketing**: 3 tiers, понятные differentiator
- **Mobile-friendly**: легче integrate с App Store / Google Play subscription IAP

### Negative / risks

- **Migration headache**: existing credit holders → goodwill credit / waiver
- **Stripe webhook complexity** — нужен реальный subscription lifecycle
- **Cancellation flow** — нужно сделать easy (regulatory + UX)
- **Free tier нужен generous** иначе нет funnel — мы сделали 30 scans/week + 3 grades/week + 100 cards collection (см. limits doc)

## Implementation order

1. Usage tracking + limits + **fix free credits bug** ([[../../20-Areas/08-webapp/known-issues]] #1)
2. Stripe subscription flow (checkout + webhooks + user role)
3. Feature gating в UI (mobile + webapp)
4. Pricing page
5. Communication к existing credit holders

## Connection с features

### Pro paywall triggers (для conversion)

- **Graded prices** (PSA 10, PSA 9 values) → Pro-only — главный pull для серьёзных collectors
- **CSV/PDF export** → Pro
- **Unlimited everything** → Pro

### Plus paywall triggers

- **Detailed Reports** → Plus minimum
- **More collection capacity** (100 → 1000 cards)
- **Watchlist 5 → 25**

### Free пользы (для retention)

- 30 scans/week unlimited price check
- 3 grades/week
- Все 3 price sources (CardMarket, TCGPlayer, eBay) — base ценность

## Rationale: pricing levels

- **$6.99** Plus — psychological "under $10", impulse purchase
- **$14.99** Pro — value-anchored relative to PSA grading ($20-150/card). Pro окупается **одной картой**.
- **~28% annual discount** ("2 months free") — стандарт industry

## When to revisit

Если:
- Conversion < 2% на любой tier (что-то с tiers/pricing)
- Churn > 10%/mo (не enough Pro stickiness)
- ARPU не растёт после 6 месяцев
- Сильное демонстрирование что collectors хотят one-time purchase

## Related

- Detailed tiers: [[../../20-Areas/11-product/monetization/tiers-free-plus-pro]]
- Webapp bug (credit purchases без payment): [[../../20-Areas/08-webapp/known-issues]]
- Implementation plan: [[../../20-Areas/11-product/monetization/implementation-order]]
- Mobile enforcement: [[../../20-Areas/07-mobile/missing-features#5-subscription-enforcement]]
- Competitors using subscription: [[../../20-Areas/11-product/competitors/ludex]] (TBD), [[../../20-Areas/11-product/competitors/collx]] (TBD)
