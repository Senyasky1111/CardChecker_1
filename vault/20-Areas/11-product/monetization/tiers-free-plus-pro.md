---
type: module
status: approved
created: 2026-05-21
updated: 2026-05-21
decided: 2026-03-22
area: [product, monetization]
tags: [pricing, tiers, subscription]
related: [[implementation-order]], [[../strategy]]
---

# Tiers: Free / Plus / Pro

> **TL;DR**: 3-tier subscription (Free, Plus $6.99/mo, Pro $14.99/mo). Принято 2026-03-22.
> Кредитная модель убрана — чистая подписка.

## Structure

| Feature | Free | Plus ($6.99/mo, $59.99/yr) | Pro ($14.99/mo, $129.99/yr) |
|---|---|---|---|
| **Scans (Price Check)** | 30/week | Unlimited | Unlimited |
| **Condition Grades** | 3/week | 50/month | 300/month |
| **Detailed Reports** | ❌ | 10/month | 50/month |
| **Collection** | 1 binder, 100 cards | 5 binders, 1000 cards | Unlimited |
| **Watchlist** | 5 cards | 25 cards | Unlimited |
| **Price Sources** | CardMarket + TCGPlayer + eBay | All | All + graded (PSA/CGC/BGS) |
| **Price History Charts** | ❌ | 30-day | Full history |
| **Country Price Filtering** | ❌ | ✅ | ✅ |
| **CSV/PDF Export** | ❌ | ❌ | ✅ |

## Key decisions

- **Scans FREE для платных** — стоимость доставки $0, нет смысла лимитировать paid users
- **Graded prices (PSA 10, PSA 9) = Pro paywall** — основной триггер апгрейда на Pro
- **Free включает все 3 price sources** — не gated. Это базовая ценность.
- **Кредитная система убрана** — чистая подписка
- **Annual discount ~28%** ("2 months free")

## Rationale

Value-based pricing относительно PSA grading: их сервис $20-150/карта, занимает недели. Наш AI grade — 5 секунд. При том что Pro = $15/мес, окупается одной картой.

## Implementation order

См. [[implementation-order]].

1. Usage tracking + limits + **fix free credits bug** ([[../../08-webapp/known-issues#1-credit-purchases-без-payment]])
2. Stripe subscription flow (checkout + webhooks + user role)
3. Feature gating в UI
4. Pricing page

## Связанные

- [[pricing-log]] — append-only история изменений
- [[feature-gating]] — где в UI блокируем
- [[implementation-order]] — порядок имплементации
- [[../competitors/_MOC]] — для сверки с ценами конкурентов
- Webapp: [[../../08-webapp/overview]]
- Mobile: [[../../07-mobile/missing-features]]
