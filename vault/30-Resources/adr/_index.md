---
type: index
status: active
created: 2026-05-21
updated: 2026-05-21
tags: [adr, index]
---

# ADR Index

> All Architectural Decision Records. Auto-listed via Dataview.

## Active decisions (most recent first)

```dataview
TABLE date AS "Date", status AS "Status", area AS "Area"
FROM "30-Resources/adr"
WHERE type = "adr"
SORT date DESC
```

## By area

```dataview
TABLE rows.file.link AS "ADR", rows.date AS "Date"
FROM "30-Resources/adr"
WHERE type = "adr"
GROUP BY area
```

## Status legend

- `proposed` — обсуждается, ещё не принято
- `accepted` — принято и в силе
- `rejected` — рассмотрено, отклонено (с rationale)
- `deprecated` — больше не релевантно
- `superseded` — заменено более новым ADR (см. `superseded-by`)

## How to write a new ADR

1. Используй template: `30-Resources/templates/adr.md`
2. Filename: `YYYY-MM-DD-short-slug.md`
3. Минимум: Context, Decision, Consequences (positive + negative)
4. Update `log.md` одной строкой: `## [YYYY-MM-DD] decision | brief`

## Connecting ADRs

- `supersedes: [[YYYY-MM-DD-old-slug]]` — если эта ADR заменяет старую
- `superseded-by: [[YYYY-MM-DD-new-slug]]` — после superseding update обе ADR

## Related

- Template: [[../templates/adr]]
- Log: [[../../log]]
