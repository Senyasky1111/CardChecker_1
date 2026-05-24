---
type: moc
status: draft
created: 2026-05-21
updated: 2026-05-23
area: [business]
tags: [moc, business]
---

# Business MOC

> Маркетинг, legal, финансы — операционка.
> Skeleton — заполняется по необходимости.

## What's filled

- [[monetization]] — subscription tier structure, ADR-backed decisions
- [[store-listing]] — App Store / Play Store copy reference

## What's planned (stubs / placeholders)

### Marketing
- [ ] Launch plan
- [ ] Content calendar
- [ ] Channels (ASO, social, paid)

### Legal
- [ ] ToS + Privacy Policy
- [ ] CardMarket / PriceCharting / TCGPlayer ToS compliance review
- [ ] Image rights review (scraped images used for ML training)

### Finance
- [ ] API costs (Gemini, RapidAPI, PokeTrace, Hetzner, Apify)
- [ ] Per-user cost model
- [ ] Revenue projection

## Conventions

This area is **lowest priority** для engineering. Заметки добавляются:
- Когда decision needs to be locked (write an ADR + entry here)
- Когда есть concrete artefact (launch playbook, contract, financial spreadsheet) to reference

Не пишем speculative business notes — это шум для Claude sessions.

## ADRs in this area

- [[../../30-Resources/adr/2026-03-22-monetization-subscription-not-credits]]
