---
type: module
status: active
source: src/config.py
lines: 28
related: [[../config-and-env]]
area: [backend]
tags: [module, config, secrets]
created: 2026-05-21
updated: 2026-05-21
---

# config.py

> **TL;DR**: Тонкий config loader. Читает `.env` из project root, экспортирует API keys и rate limit constants.

## Public surface

### Constants

| Name | Source | Default |
|------|--------|---------|
| `POKETRACE_API_KEY` | `.env` POKETRACE_API_KEY | "" |
| `POKEMON_API_RAPIDAPI_KEY` | `.env` POKEMON_API_RAPIDAPI_KEY | "" |
| `GEMINI_API_KEY` | `.env` GEMINI_API_KEY | "" |
| `POKETRACE_BASE_URL` | hardcoded | `https://api.poketrace.com/v1` |
| `POKEMON_API_BASE_URL` | hardcoded | `https://pokemon-tcg-api.p.rapidapi.com` |
| `POKETRACE_BURST_DELAY` | hardcoded | 0.35s (~3 req/s, complies с 30 req/10s) |
| `POKEMON_API_DELAY` | hardcoded | 0.25s (~4 req/s, complies с 300 req/min) |

## Internal flow

1. Load `.env` из project root (parent of `src/`)
2. `os.environ.setdefault(key, value)` — не перезаписывает existing env vars

## Notable patterns

- **`.env`-based** — secrets management без коммита в git
- Rate limit compliance: PokeTrace ~3 req/s, Pokemon-API ~4 req/s
- Soft load: пустые keys → endpoints возвращают 503 (graceful)

## `.env` template

```bash
GEMINI_API_KEY=AIzaSy...
POKETRACE_API_KEY=...
POKEMON_API_RAPIDAPI_KEY=...
```

Файл `.env` уже в `.gitignore` — не закоммитится.

## Связанные

- Env vars documentation: [[../config-and-env]]
- Gemini consumers: [[gemini_grade]], [[gemini_identify]]
- API endpoints что dependent: [[../endpoints/gemini-identify]], [[../endpoints/gemini-grade]]
