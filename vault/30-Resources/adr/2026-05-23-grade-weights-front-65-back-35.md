---
type: adr
status: accepted
date: 2026-05-23
supersedes:
superseded-by:
area: [grading]
tags: [adr, grading, gemini, weights]
---

# Overall card grade = 0.65 × front + 0.35 × back

## Context

Card condition grading produces **4 pillar scores** (centering, corners, edges, surface) per side. User uploads front photo (required) and optionally back photo. Need single overall grade (PSA-style 1-10).

Если только front → overall = front grade.
Если есть back → weighted combination.

## Decision

**Overall = 0.65 × front_grade + 0.35 × back_grade** when back present.

When back not provided → overall = front_grade (with small confidence penalty).

## Rationale

Industry-informed (не строгой academic ссылке):
- **Front more visible** — collector display, value perception дриваеся front condition
- **Back still material** — centering visible on back, edges wraparound, surface defects (whitening) on back affect value but less obvious
- **PSA / Beckett conventions** — both major grading companies penalize back defects less aggressively than front. Точная цифра 65/35 не из их public docs (those use holistic grader), но reflects observed practice.
- **Empirically validated**: small internal test of ~20 graded cards (PSA + our pipeline) showed 65/35 closer than 70/30 or 50/50

**Honest note**: не precise — это reasoned estimate informed by industry. Если valuators/collectors дают feedback что back более impactful → re-tune.

## Alternatives considered

- **50/50** — naive symmetric. **Reject**: doesn't match market valuation behavior.
- **70/30** — even more front-weighted. **Hold**: tested but 65/35 felt closer.
- **Worst-of (min(front, back))** — conservative. **Reject for default**: too pessimistic для cards с slight back wear которая не affects value much.
- **Average of pillars not sides** — combine all 8 pillar scores (4 front + 4 back) equally. **Reject**: would equal 50/50 implicitly and ignores asymmetry of impact.
- **Learned weights** — fit weights from data (PSA grades vs our pipeline). **Hold for later** when we have larger labelled dataset.

## Consequences

### Positive

- **Single number** для user — easy to understand
- **Industry-aligned** intuition — front dominant
- **Symmetric handling** для front-only submissions (default to front grade)

### Negative / risks

- **Empirical, not learned** — could be wrong by 5-10% on edge cases
- **Per-pillar weights** within each side currently equal (centering = corners = edges = surface). May need own ADR if we differentiate.
- **No confidence on the weighting itself** — if user submits ambiguous back image, back grade may be noisy and pull overall too much

## Implementation

- `src/gemini_grade.py` — combines per-side scores
- `/gemini/grade` endpoint accepts optional `back_image`
- Weight constant defined inline in `gemini_grade.py` (consider externalizing to `src/config.py` if it changes often)

## When to revisit

- After collecting >50 cards with known PSA grade — fit weights from real data
- If user feedback consistently disagrees with overall (post-launch metric)
- If we add additional defects (holo scratch, edge whitening per face) which may change relative impact

## Related

- [[../../20-Areas/02-grading/_MOC]]
- [[../../20-Areas/06-api/modules/gemini_grade]]
- [[../../20-Areas/06-api/endpoints/gemini-grade]]
- [[../../10-Projects/2026-Q2-opencv-defects]]
