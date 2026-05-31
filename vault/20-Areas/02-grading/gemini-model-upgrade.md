---
type: deliberation
status: open
created: 2026-05-24
updated: 2026-05-24
area: [grading, ml]
tags: [gemini, model-upgrade, deliberation]
related: [[_MOC]], [[../../30-Resources/adr/2026-03-21-gemini-for-grading-not-custom-model]], [[../../10-Projects/2026-Q2-opencv-defects]]
---

# Gemini Model Upgrade — Open Deliberation

> **TL;DR**: Defect detection сейчас на Gemini 2.5 Flash. До того как YOLO26x-OBB defect detector доедет (Project #2 Phases 3-4, требует GPU + TAG annotation), может стоить upgrade на более сильную VLM как interim. Опции и tradeoffs ниже.

## Why consider upgrading

- **Phase shift**: defect-detection ML pipeline (Project #2) — серьёзная работа, может растянуться (TAG SPA reverse-engineer + Gemini-assisted annotation + GPU training). До этого есть месяцы where grading качество = качество текущей VLM.
- **Gemini 2.5 Flash** — был выбран в марте 2026 (см. [[../../30-Resources/adr/2026-03-21-gemini-for-grading-not-custom-model|ADR]]) как balance accuracy/cost/latency. Качественные VLM landscape с тех пор сильно изменился.
- **Known failure modes** Gemini Flash (per [[_MOC]]): missed субtle whitening, occasional hallucinated defects на clean cards, sometimes inconsistent scoring across re-runs of same image.

## Candidates (2026 landscape)

### Gemini family
- **Gemini 2.5 Pro** — same family, more compute, better vision reasoning. ~5-10× cost, ~2-3× latency. Easy migration (same API).
- **Gemini 3.0 Flash / Pro** (если released к май 2026) — newer generation, likely better visual accuracy.

### Anthropic
- **Claude Opus 4.7** — vision capable, strong reasoning. Cost higher than Gemini Flash, comparable to Gemini Pro.
- **Claude Sonnet 4.6** — middle tier, fast, strong visual capabilities. Could be similar cost to Gemini Pro.

### OpenAI
- **GPT-5** (если released) / **GPT-4o** — strong vision, mature ecosystem. Cost competitive c Gemini Pro.

### Specialized / open-source
- **Qwen2.5-VL** / **InternVL3** — open-source SOTA VLMs. Self-host = no API cost, but GPU required.
- **Card-specific fine-tune** — fine-tune VLM на our internal grading data. Long-term play, requires data labelling effort.

## Decision factors

| Factor | Weight | Notes |
|---|---|---|
| **Visual accuracy on cards** | High | Need benchmark — нет existing comparison data |
| **Cost per grade** | Medium | Gemini Flash ~$0.001 / grade; Pro ~$0.005-0.01 |
| **Latency** | Medium | Current 3-5s acceptable; <10s still OK |
| **API maturity / reliability** | Medium | Gemini, Claude, OpenAI all production-grade; OSS self-host adds ops |
| **Privacy / data control** | Low (for now) | Cards aren't PII; minor concern |
| **Migration effort** | Low | All API-based VLMs ≈ swap |

## Recommended path (no decision yet)

1. **Benchmark** — взять 50 cards с known grades (TAG ground truth есть), run через 3-4 candidates, compare:
   - Per-pillar score MAE vs ground truth
   - Defect detection precision/recall (do they identify same defects as humans?)
   - Cost per run
   - Latency
2. **Pick winner**, write ADR locking decision.
3. **A/B test** в production с canary 5% traffic, monitor user-reported wrong-grade rate.

## Estimated effort

- Benchmark setup: 1 day (~50 cards × 4 models)
- Migration: <0.5 day (swap API call)
- Total: ~1.5 days до production rollout

## Decision status

**OPEN** — пока в deliberation. Не блокирует другие приоритеты, но имеет высокий ROI потенциал если current Gemini Flash и впрямь у нас bottleneck.

Когда принимаем — пишем ADR (supersedes 2026-03-21).

## Связанные

- ADR (current state): [[../../30-Resources/adr/2026-03-21-gemini-for-grading-not-custom-model]]
- Defect detection roadmap: [[../../10-Projects/2026-Q2-opencv-defects]]
- Grading module: [[../06-api/modules/gemini_grade]]
- 4 pillars architecture: [[defect-detection/architecture]]
