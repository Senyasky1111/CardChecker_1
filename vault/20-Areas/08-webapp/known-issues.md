---
type: module
status: active
created: 2026-05-21
updated: 2026-05-21
area: [webapp]
tags: [issues, bugs]
related: [[overview]], [[feature-status]]
---

# Webapp Known Issues

> **TL;DR**: Список проблем по приоритету. Снимок на 2026-03-22, могло измениться — проверь актуальность по коду.

## 🔴 Critical

### 1. Credit purchases без payment
`Account.jsx:54-73` — `handlePurchaseCredits` создаёт `CreditTransaction` **напрямую** без реального чарджа Stripe. **Любой может бесплатно добавлять кредиты**.

### 2. Blob URL images ломаются
Collection items и Reports хранят `blob://` URL'ы — они **умирают** после перезагрузки страницы. Изображения исчезают.

Fix needed: persistent storage (Base44 file storage или S3) вместо blob URL'ов.

### 3. Stripe subscription stub
В dev режиме возвращает `{ url: null }`. В Base44 prod — Stripe Checkout Session.
**Missing**: webhook handling, subscription status tracking, feature gating.

## 🟡 UX / Feature

### 4. DollarSign icon на "Start Scanning"
`Scan.jsx` lines 7, 85, 224 — должна быть Camera/ScanLine иконка, не DollarSign.

### 5. Portfolio tracking — placeholder
`Collection.jsx:218-222` — "Portfolio tracking coming soon". Данные есть, нужен только UI.

### 6. Price History — placeholder
`PriceHistoryChart.jsx` — recharts установлен, компонент пустой.

### 7. Detailed Report скрыт
`Layout.jsx:51` — `ready: false` показывает "Soon" badge, не кликабельно.

### 8. Watchlist без polling
`current_price` никогда не обновляется, alerts никогда не срабатывают.

### 9. Report.jsx неэффективный fetch
`Report.jsx:32` — `Report.list().find(...)` вместо `.get(id)` — O(n) вместо O(1).

## 🟢 Issues в `ReportNew.jsx` (когда включим)

- `authenticity_score` hardcoded в 95 (line 228)
- `centering_grid` использует `frontUrl` как placeholder (line 207)
- Defect pins все в x:50, y:50 — без реальных координат (line 214-215)
- Video uploaded как blob URL — не переживёт reload
- `publicHash` рандомный, не валидируется (line 197)

## 🔵 Backend Integration нужен

- **Price history endpoint** — `/card/{id}/price-history` не реализован в FastAPI
- **Image upload** — нужен persistent storage вместо blob URLs
- **Watchlist price polling** — background job обновлять `WatchItem.current_price`
- **Subscription webhook** — Stripe → update user role/tier в Base44

## Связанные

- [[overview]]
- [[feature-status]]
- Monetization fix order: [[../11-product/monetization/implementation-order]]
