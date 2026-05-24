---
type: moc
status: active
created: 2026-05-21
updated: 2026-05-21
area: [meta]
tags: [moc, projects]
---

# Projects MOC

> Активные **спринты** на Q-level. Когда закончены — переезжают в `40-Archive/`.

## 2026 Q2 (текущие приоритеты)

```dataview
TABLE status, area FROM "10-Projects"
WHERE !contains(file.name, "_MOC")
SORT file.name
```

## Связанные

- Index: [[../index]]
- Backlog в Product MOC: [[../20-Areas/11-product/roadmap]]
