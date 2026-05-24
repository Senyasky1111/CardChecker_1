---
type: context-pack
status: active
created: 2026-05-21
updated: 2026-05-21
tags: [context-pack, monetization, product]
---

# Context Pack: Monetization Decisions

> **Use when**: Обсуждаем pricing, tier feature gating, новые фичи и как их монетизировать.

## Approved tier structure

![[../20-Areas/11-product/monetization/tiers-free-plus-pro]]

## Webapp-side bugs related to monetization

См. [[../20-Areas/08-webapp/known-issues]]:
- Credit purchases без payment (critical bug)
- Stripe subscription stub
- Нет webhook handling

## Where the gating goes

- **Mobile**: пока нет — нужно добавить
- **Webapp**: см. `Layout.jsx` + entity-level checks в Base44

## Pricing rationale

- Pro $14.99/mo окупается одной картой (PSA grading = $20-150/карта, недели)
- Annual discount ~28% ("2 months free")
- Кредитная система **убрана** — чистая подписка

## Key triggers для апгрейда

- Free → Plus: Watchlist > 5 cards, Collection > 100 cards, нужны Detailed Reports
- Plus → Pro: graded prices (PSA 10/9), CSV/PDF export, unlimited

## Не забывать

- Free scans **остаются unlimited** — стоимость доставки $0
- 3 price sources на Free — base ценность
- Graded prices = Pro paywall trigger
