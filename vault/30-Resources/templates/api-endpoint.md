---
type: api-endpoint
method:
path:
status: active
latency-p95:
source: src/api.py
related: []
area: [backend, api]
tags: [api]
created: <% tp.date.now("YYYY-MM-DD") %>
updated: <% tp.date.now("YYYY-MM-DD") %>
---

# <% tp.file.title %>

> **TL;DR**: <!-- одна строка: что делает и когда использовать -->

## Request

```http
{{method}} {{path}}
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
|       |      |          |             |

## Response

```json
{
}
```

## Pipeline

<!-- Что происходит внутри. Линки на модули. -->

1. 
2. 
3. 

## Failure modes

- **{{code/error}}**: when and why
- 

## Performance

- Typical: ~Xms
- p95: 
- Bottleneck: 

## Recent changes

- [[<% tp.date.now("YYYY-MM-DD") %>]] — initial doc

## Related

- Module: [[ ]]
- ADRs: [[ ]]
