---
type: module
status: critical
created: 2026-05-21
updated: 2026-05-21
area: [ops]
tags: [deploy, safety, critical, rules]
related: [[deploy-procedure]], [[hetzner-server]]
---

# ⚠️ Deploy Safety Rules

> **READ BEFORE EVERY DEPLOY.** Эти правила существуют потому что мы один раз обожглись и не хотим повторно.

## The rules

### 1. NEVER deploy untested code

- Каждый файл должен быть протестирован **локально** перед уплоадом
- "It should work" — не критерий. Нужен **запуск**.
- Smoke test minimum: импорт, базовый endpoint работает

### 2. ONLY deploy specific intended files

- НЕ деплой "всё подряд" — `git diff` показывает что реально меняется
- Знай **точно** какие файлы пушишь
- Используй single-file deploy если правится один скрипт

### 3. NO rollback exists on the server

- Старая версия **не сохраняется** автоматически
- Если ты сломал прод — никто тебя не спасёт кроме твоей локальной копии
- **Прежде чем deploy** — убедись что локальная версия точно рабочая

### 4. Database is sensitive

- `data/cards.db` содержит pricing и метаданные **всех 50K карт**
- Если случайно перезаписал старой версией — ты потерял дни-недели работы скраперов
- **Перед DB deploy**: backup существующей на сервере

### 5. Models are large, не overwrite случайно

- `models/` уже на сервере
- НЕ включай `models/` в tarball'ы случайно — это съест время и трафик
- Если нужно обновить модель — это **отдельный** intentional deploy

### 6. Secrets stay local

- `.env` содержит API keys
- Деплоится осознанно
- НЕ коммить в git (есть `.gitignore`)

## Pre-deploy checklist

- [ ] Локально протестировано (smoke + targeted)
- [ ] Знаю точно какие файлы меняются (`git diff --stat`)
- [ ] Если меняю DB — есть backup существующей prod версии
- [ ] Не включаю `models/`, `venv/`, `data/cardmarket/`, `data/tag_*` случайно
- [ ] Я готов SSH'нуться и откатиться если что-то сломается

## Post-deploy verification

- [ ] `/health` отвечает 200
- [ ] Хотя бы один real endpoint проверен (`/identify-v2`, `/card/{id}`)
- [ ] Логи без новых ошибок (`docker compose logs --tail=100`)

## Past mistakes (write them here!)

<!-- Когда что-то пойдёт не так — записать сюда, чтобы не повторить -->

- (placeholder — пока без инцидентов в новой структуре)

## Связанные

- [[deploy-procedure]] — пошаговая инструкция
- [[hetzner-server]] — описание прода
- [[runbooks/server-recovery]] — если всё-таки сломал
