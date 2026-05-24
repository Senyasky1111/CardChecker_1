---
type: note
status: stable
area: [mobile, frontend]
tags: [mobile, components, ui]
created: 2026-05-23
updated: 2026-05-23
---

# Mobile Components Overview

> 38 компонентов в `mobile/src/components/`. Группированы по роли. Sweeping — не per-file, открой исходник если нужны детали.

## UI Primitives (design system core)

| Component | Purpose |
|-----------|---------|
| `Button.tsx` | Pressable + haptics, primary/secondary/ghost variants |
| `Text.tsx` | Styled text wrapper (consistent typography) |
| `Input.tsx` | Text field |
| `Divider.tsx` | Visual separator |
| `GlassCard.tsx` | Glassmorphism frame (used широко для cards / panels) |
| `Skeleton.tsx` | Loading placeholder |
| `GradientBackground.tsx` | Animated gradient backdrop |
| `Badge.tsx` | Generic tag |
| `RarityBadge.tsx` | Rarity-specific badge (common/uncommon/rare/holo/secret) |
| `LanguageBadge.tsx` | EN/JP/TW chip |
| `PriceTag.tsx` | Formatted price display |
| `ConfidenceBadge.tsx` | OCR/CLIP confidence visualization |

## Layout

| Component | Purpose |
|-----------|---------|
| `Screen.tsx` | Safe area + scroll container wrapper. Wraps every screen. |
| `TabBar.tsx` | Bottom navigation (used by `(tabs)/_layout`) |
| `EmptyState.tsx` | Placeholder для пустых lists |
| `ErrorState.tsx` | Error fallback UI |

## Card domain (identification + display)

| Component | Purpose |
|-----------|---------|
| `PokemonCard.tsx` | Card image с purple glow frame, sm/md/lg sizes |
| `CardMarketLink.tsx` | Button — opens CardMarket URL в browser |
| `PriceGrid.tsx` | Multi-source price grid (CardMarket / TCGPlayer / eBay) |

## Grading domain

| Component | Purpose |
|-----------|---------|
| `DefectHeatmap.tsx` | Card image с colored defect zones; tap → defect description |
| `GradeBadge.tsx` | Overall grade (6.5, 8.0, etc.) |
| `SubgradeRow.tsx` | Per-pillar score (centering/corners/edges/surface) |
| `GradeDistributionChart.tsx` | Bar chart subgrades |
| `GradingHistoryCard.tsx` | Past grading entry в history list |
| `DefectList.tsx` | Ordered list defects с severity |
| `PhotoSlotGrid.tsx` | Multi-slot photo capture (front/back/holo/angle) |
| `GradingServiceSelector.tsx` | Choose service (internal/PSA/BGS/CGC) |
| `ROICalculator.tsx` | Grading ROI estimator |
| `GradingPaywall.tsx` | Upsell для pro grading |

## Collection domain

| Component | Purpose |
|-----------|---------|
| `CollectionCard.tsx` | Single card в portfolio grid |
| `CollectionStats.tsx` | Summary (total value, qty, avg grade) |

## Scan domain

| Component | Purpose |
|-----------|---------|
| `CameraViewfinder.tsx` | Live camera preview |
| `ScanButton.tsx` | Large scan trigger |
| `ScanLoadingAnimation.tsx` | Scanning progress animation |

## Conventions

- **Domain prefix** — `Grade*`, `Collection*`, `Scan*` для domain-specific. Primitives без prefix.
- **One file per component**, no barrel `index.ts` exports — Expo bundler tolerates это лучше для tree-shaking
- **Props через TypeScript interface** прямо над компонентом, не в `types.ts`
- **Styles inline через StyleSheet.create** в конце файла (RN convention)
- **No CSS-in-JS libraries** — pure StyleSheet
- **Theme tokens** из `src/theme/` (colors, spacing, typography, shadows, animations)

## When adding new component

1. Determine category (UI / Layout / domain-X)
2. Check existing — может уже есть похожее
3. Place в правильный subfolder (note: actually flat в src/components/, categorization conceptual)
4. Add row в этой заметке если non-trivial

## Related

- [[architecture]]
- [[screens-overview]] — где компоненты используются
- `mobile/src/theme/` — design tokens
