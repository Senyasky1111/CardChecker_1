---
type: log
status: active
area: [ml]
tags: [experiments, log]
created: 2026-05-23
updated: 2026-05-23
---

# ML Experiments Log

> Append-only журнал что пробовали, какие гипотезы, какие результаты. **Не путать с** [[../../../log|main log.md]] (general project journal).

Формат записи:
```
## YYYY-MM-DD — <slug>
**Hypothesis**: ...
**Setup**: model, data, hyperparams
**Result**: numbers + qualitative
**Verdict**: continue / abandon / hold
**Artefacts**: paths/runs
```

---

## 2026-05-23 — backfill log creation

Vault docs reorganized; experiments log started fresh as part of vault overhaul. Past experiments not retroactively logged (most were prior to vault existence). Going forward, every training run / non-trivial benchmark adds an entry here.

**Verdict**: log structure established. Will populate from next experiment onwards.

---

## Backlog (planned experiments)

Used to track what should be tried next, even before starting:

- **CLIP fine-tune full run** — pretrained vs fine-tuned retrieval@1 на 500-image labelled holdout. Pending: labelled holdout collection finalized.
- **YOLOv11n vs YOLOv8n для card detector** — small accuracy bump possible. Quick swap test.
- **Defect YOLO confidence calibration** — per-class threshold для optimal precision при acceptable recall. Pending: enough validation data.
- **EasyOCR primary for JP cards** — does accuracy gain justify latency? Bench on holdout.
- **doctr full integration** — currently narrow use; possible broader replacement of Tesseract for non-EN.

---

## Related

- [[_MOC|ML Research MOC]]
- [[../../../log|Main project log]]
