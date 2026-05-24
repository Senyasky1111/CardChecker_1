---
type: runbook
status: active
area: [data-pipelines, pricing]
tags: [runbook, prices, daily, cron]
created: 2026-05-23
updated: 2026-05-23
---

# Runbook — Daily Price Update

> `scripts/update_prices_daily.py` (~839 строк). Scheduled task на windows via `update_prices.bat` + `setup_scheduler.bat`.

## Что делает

Daily refresh of price data для всех ~50K cards. Сорсы:
1. **PokeTrace Pro API** — primary, gives USD/EUR + PSA/BGS/CGC graded prices
2. **Pokemon-API** — supplementary US market data
3. **CardMarket CSV** — EU market snapshot (downloaded daily)

Final write: bulk `UPDATE` в `data/cards.db`.

## Когда запускается

- **Cron**: ~03:00 local time (chosen to be off-peak для API providers)
- **Schedule mechanism**: Windows Task Scheduler через `setup_scheduler.bat`
- **Trigger script**: `update_prices.bat` (calls Python script)

## Inputs

- `data/cards.db` — source of card IDs to refresh
- `data/cardmarket_csv/<date>.csv` — daily CM dump (downloaded separately, see [[../cardmarket/overview]])
- API credentials в `.env`: PokeTrace, Pokemon-API

## Outputs

- Updates `prices` table в `cards.db`
- Logs to `logs/update_prices_<date>.log`
- Skipped cards (no match) accumulated в `logs/skipped_<date>.csv`

## Failure modes

- **API rate-limit (429)** — script retries with exponential backoff, max 3 retries. После — skip card, log.
- **PokeTrace timeout** — fall back to Pokemon-API only. Some cards stay stale.
- **CM CSV missing** — EU prices not refreshed that day. Log warning.
- **DB lock** — if API serving + update collide. WAL mode mitigates but during write transactions reads may be slowed. Should be rare given 03:00 schedule.

## Monitoring

- Check `logs/update_prices_<date>.log` next morning
- Skipped cards count > threshold (~5%) — investigate
- DB freshness: `SELECT MAX(updated_at) FROM prices` should be today

## Manual run

```bash
./venv/Scripts/python.exe scripts/update_prices_daily.py
```

Optional flags (read top of file для current options):
- `--lang en|jp|tw` — partial refresh
- `--limit N` — first N cards only (testing)
- `--dry-run` — no DB writes

## Related

- [[../scripts-catalog#Pricing Enrichment (5)]]
- [[../../03-pricing/_MOC]]
- [[../../10-infrastructure/_MOC]]
- [[../../../10-Projects/2026-Q2-live-pricing]] — eventual goal: move to live API instead of daily snapshot
