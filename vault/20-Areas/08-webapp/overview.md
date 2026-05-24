---
type: module
status: active
created: 2026-05-21
updated: 2026-05-21
area: [webapp, frontend]
tags: [base44, webapp, stripe]
source: https://github.com/Senyasky1111/CardChecker_MVP
related: [[architecture]], [[feature-status]]
---

# CardChecker Webapp Overview

> **TL;DR**: Параллельный продукт — веб-приложение на Base44, использует тот же FastAPI бэкенд что мобильное приложение.
> Домен: [cardchecker.app](https://cardchecker.app) · Backend: `bees.cardchecker.app`

## Stack

- **Platform**: Base44 (React + Vite + `@base44/sdk`)
- **UI**: Tailwind + 60+ shadcn/Radix components, framer-motion для переходов
- **Data**: `@tanstack/react-query`
- **Payment**: Stripe (`@stripe/react-stripe-js`)
- **Charts**: recharts (установлен, не используется — план для price history)
- **Other**: jspdf + html2canvas (для PDF экспорта, не используется)

## Repository

- GitHub: [Senyasky1111/CardChecker_MVP](https://github.com/Senyasky1111/CardChecker_MVP)
- Local clone: `D:\amotrychenko\Desktop\CardChecker_MVP` (отдельный репо, не в этом vault'е)

## Base44 Entities (CMS/DB)

- **User** — role, email, full_name
- **CreditTransaction** — amount, reason (`purchase`/`report`), balance_after
- **Report** — card_name, set_name, images, centering, whitening, defects, grade, pricing, authenticity_score, public_hash
- **Binder** — name, created_by
- **CollectionItem** — binder_id, card_name, set_name, front_image_url, current_value, quantity
- **WatchItem** — card_name, set_name, target_price, alert_enabled, current_price

## Pages — статус

| Page | Статус |
|------|--------|
| `Scan.jsx` (landing/hero) | ✅ работает |
| `PriceScanner.jsx` | ✅ **полностью работает** |
| `ConditionCheck.jsx` | ✅ **полностью работает** |
| `ReportNew.jsx` (detailed report) | ⚠️ 80% готов, **скрыт в навигации** (`ready: false` в Layout.jsx:51) |
| `Report.jsx` | ⚠️ работает, но blob URL'ы ломаются после перезагрузки |
| `Collection.jsx` | ✅ работает |
| `Watchlist.jsx` | ⚠️ нет polling'а цен |
| `Account.jsx` | ⚠️ credit purchases без payment, Stripe stub в dev |
| `Admin.jsx` | ✅ работает |

См. подробности в [[feature-status]] и [[known-issues]].

## API integration (`cardcheckApi.js`)

- `API_BASE`: `VITE_CARDCHECK_API_URL || 'https://bees.cardchecker.app'`
- `identifyCardSmart()`: `/identify-v2` → fallback `/gemini/identify` (threshold 0.50)
- `gradeCard()`: `/gemini/grade` (front + optional back)
- `detectCard()`: `/detect-card?visualize=true&backend=auto`
- `getCardPrices()`: `/card/{tcgdex_id}/prices`
- `healthCheck()`: `/health`

## Stripe Integration

- Serverless function: `base44/functions/createSubscriptionCheckout/entry.ts` (Deno + Stripe v14)
- Price ID: `price_1T7N2rPVtgYLRHJWfRTtocR7`
- В dev: stub возвращает `{ url: null }`
- ⚠️ **Missing**: webhook handling, subscription status tracking, feature gating

## Связанные

- API: [[../06-api/_MOC]]
- Mobile (sibling product): [[../07-mobile/_MOC]]
- Monetization: [[../11-product/monetization/tiers-free-plus-pro]]
- Webapp vs Mobile strategy: [[webapp-vs-mobile-strategy]]
