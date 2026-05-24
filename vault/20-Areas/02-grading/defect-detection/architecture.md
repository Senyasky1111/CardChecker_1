---
type: module
status: planned
created: 2026-05-21
updated: 2026-05-21
decided: 2026-03-21
area: [grading, ml]
tags: [defect-detection, yolo, multi-angle, gpu]
related: [[../_MOC]], [[training-tracks]], [[tag-data-pipeline]]
---

# Defect Detection — Architecture

> **TL;DR**: 8 архитектурных решений принято 2026-03-21.
> Server-side GPU + multi-angle capture + YOLO26x-OBB + TAG data в качестве основного источника обучения.

## 1. Server-side GPU (НЕ on-device)

- Грейдинг **не real-time** — пользователь ждёт 3-5 сек, это ОК
- GPU позволяет YOLO26x-OBB (~130MB, максимальная точность) вместо YOLO26n (~6MB)
- Открывает доступ к SAM2, DINOv2, RF-DETR
- Никаких компромиссов размера/квантизации
- **Action**: Arsenii покупает GPU для Hetzner

**Почему**: качество = priority #1, latency budget = 3-5s не 300ms.

## 2. Multi-angle capture (3-5 фото)

- **3 front photos**: top-down + ~20° left + ~20° right + опциональный flash + 1 back
- Все warped в каноничный **600×825** через гомографию (углы карты → фиксированные координаты)
- Карта плоская 63×88mm → гомография **точная**
- **Defect fusion**: union детекций со всех ракурсов
- **Specular reflection filter**: bright на одном ракурсе, normal на другом = **НЕ defect** (решает проблему голо-карт)
- Angle-dependent дефекты (царапины) видны на 1/N ракурсов
- Structural дефекты (crease, whitening) видны на всех N
- **UI**: guided silhouette + arrow как при panoramic capture

**Почему**: одно фото пропускает angle-dependent defects (голо-царапины, глубина whitening краёв, помятые углы).

## 3. Single YOLO26x-OBB (НЕ MobileNetV3 per-region)

- Одна модель — проще maintenance, deployment, versioning
- OBB даёт class + точный oriented bbox
- YOLO26 STAL хорошо ловит мелкие объекты (whitening spots)
- MobileNetV3 per-region требует ROI extraction = больше точек отказа
- **Centering остаётся чистым OpenCV** (детерминистично, 0ms ML overhead)

## 4. TAG data = primary training source

- TAG DIG reports public: `my.taggrading.com/card/{CERT#}`
- Pop report даёт cert номера: `my.taggrading.com/pop-report`
- SPA app — нужен reverse engineering API (DevTools → network)
- **60K+ Pokemon карт, ~100K+ всего**

### Что TAG даёт ✅

- HD фото front + back — **training images**
- 8 sub-grades (front/back × centering/corners/edges/surface) — 1000-point scale, **regression targets**
- Overall TAG Score (1000-point) — **grade target**
- DINGS (defect descriptions per category + count) — **class labels**
- Card Vision overlay (photometric stereo surface map) — **extra input channel**
- Centering measurements (L/R, T/B ratios) — **centering ground truth**

### Что TAG НЕ даёт ❌

- НЕТ pixel-level defect coordinates
- НЕТ bounding boxes
- Card Vision = raw surface topology, **НЕ labeled defect heatmap**
- DINGS = текстовые описания, **НЕ structured x,y coords**
- Извлечение масок из overlay требует своего CV pipeline (diff → threshold → contours)

## 5. Three training tracks

См. подробности в [[training-tracks]].

| Track | Input | Output | Архитектура |
|-------|-------|--------|-------------|
| **A** — Grade Predictor | photo | 8 sub-grades (regression) | ConvNeXt/EfficientNet-V2 + 8 regression heads |
| **B** — Defect Detector | photo | OBB defect boxes + class | YOLO26x-OBB |
| **C** — Centering | photo | L/R, T/B ratios | Pure OpenCV (Sobel + border) |

## 6. Data tiering

- **Tier 0**: TAG DIG reports — 60K Pokemon, sub-grades + DINGS + HD photos
- **Tier 1**: PSA/BGS graded с eBay — 50-100K, cert lookup → grades, real-world phone photos
- **Tier 2**: User submissions + Gemini — растёт с userbase, weak labels, human-in-the-loop

## 7. Defect classes (12)

```
corner_whitening, corner_bend, corner_blunting,
edge_whitening, edge_chip, edge_nick,
surface_scratch, surface_crease, surface_print_defect, surface_stain,
silvering, indent
```

## 8. Grade combiner

```
Centering   → OpenCV (deterministic)
Corners     → YOLO26x OBB detections
Edges       → YOLO26x OBB detections
Surface     → YOLO26x + Gemini ensemble
    ↓
4 sub-grades → BGS-style overall
    ↓
Defect heatmap overlay + DINGS (top defects affecting grade)
```

## Next steps

1. ~~Save plan to docs/DEFECT_DETECTION_PLAN.md~~ → done, теперь живёт здесь
2. Image Quality Gate — pure OpenCV, fastest win
3. OpenCV centering — Sobel + border detection
4. Reverse-engineer TAG SPA API (DevTools → network → endpoints)
5. TAG scraper → structured data ← **частично сделано** ([[../../05-data-pipelines/tag-scraping/overview]])
6. Gemini-assisted annotation pipeline
7. YOLO26x-OBB training

## Связанные

- TAG pipeline: [[../../05-data-pipelines/tag-scraping/overview]]
- TAG CDN migration история: [[../../05-data-pipelines/tag-scraping/cdn-migration-cloudfront]]
- ML training: [[../../09-ml-research/defect-yolo/strategy]]
- Project: [[../../../10-Projects/2026-Q2-opencv-defects]]
- Skill: `/defect-grader`
