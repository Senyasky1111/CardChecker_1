---
type: weekly-review
week: <% tp.date.now("YYYY-[W]ww") %>
created: <% tp.date.now("YYYY-MM-DD") %>
tags: [review, weekly]
---

# Weekly Review <% tp.date.now("YYYY-[W]ww") %>

## Decisions this week

```dataview
LIST file.link
FROM "30-Resources/adr"
WHERE date >= date(today) - dur(7 days)
SORT date DESC
```

## Notes touched

```dataview
LIST FROM ""
WHERE file.mtime >= date(today) - dur(7 days)
  AND !contains(file.folder, "_daily")
  AND !contains(file.folder, "venv")
SORT file.mtime DESC
LIMIT 25
```

## Orphan check

```dataview
LIST FROM ""
WHERE length(file.inlinks) = 0
  AND !contains(file.folder, "_daily")
  AND !contains(file.folder, "templates")
  AND file.name != "log"
  AND file.name != "index"
SORT file.name
```

## What shipped

- 

## What blocked / dropped

- 

## Next week — top 3

- [ ] 
- [ ] 
- [ ] 

## Note to future self

<!-- Что важно помнить -->
