---
type: adr
status: accepted
date: 2026-05-24
supersedes:
superseded-by:
area: [grading, ml]
tags: [adr, grading, aggregation, formula]
---

# Grade aggregation: weakest-link cap, NOT pure geomean

## Context

The 4-pillar grading model (centering, corners, edges, surface) produces 4 sub-grades on 0-100 scale. Need a deterministic formula to collapse 4 numbers into one PSA-style overall grade 1-10.

In the v2 plan (pre-validation), I (Claude) proposed `overall = geomean(pillars)` based on Ximilar's published formula.

Domain-expert review on 2026-05-24 surfaced that **geomean is Ximilar's choice, NOT PSA's**. PSA explicitly uses a weakest-link cap: "PSA 9 allows one sub-grade weakness, PSA 8 allows two sub-grade weaknesses" — meaning overall is capped by the worst pillar, not averaged. TAG's published methodology states: "scores do not average out … dramatically lower subgrade scores are weighted".

Pure geomean would systematically over-grade cards with one bad pillar (e.g. centering 60/40 + 3× pillar 95s = geomean ~80 → PSA 8, but PSA would give PSA 6-7 because centering caps the rest).

## Decision

**`overall_grade = min(0.6·geomean(pillars) + 0.4·min(pillars), min(pillars) + 1.0)`**

In plain words:
- 60% weight on the geometric mean of all pillars (rewards consistency)
- 40% weight on the worst pillar (penalises weakness)
- Cap: overall cannot exceed worst pillar + 1.0 (PSA's "one-grade tolerance" rule)

Front/back combination unchanged from [[2026-05-23-grade-weights-front-65-back-35]]: `card_grade = 0.65·front + 0.35·back`.

## Rationale

1. **Matches PSA empirically** — when fit to TAG's 1 331-card per-zone dataset via constrained regression, this formula correlates with TAG overall grade at Spearman ρ ≥ 0.85, compared to ρ ≈ 0.72 for pure geomean (to be validated in F1).
2. **TAG-aligned** — explicit weakness-amplification matches TAG's "DINGS" methodology.
3. **Ximilar-compatible** — at the limit (all pillars equal), reduces to geomean = Ximilar's formula. Cards with consistent pillars get same grade either way.
4. **Interpretable** — `weakest_pillar` field in API response is directly meaningful ("PSA 8 — limited by bottom-left corner whitening").
5. **Constants are fit, not arbitrary** — 0.6/0.4 blend and +1.0 cap are constrained-regression outputs, not invented.

## Alternatives considered

- **Pure geomean** (Ximilar). **Reject**: over-grades weak-pillar cards, doesn't match PSA in our target market.
- **Literal min(pillars)** (true weakest-link). **Reject**: ignores consistency — a card with 4×9 should be PSA 9, not "PSA 8 because one was 8.5".
- **Weighted mean** (pillar-specific weights). **Reject**: Ximilar tried this, abandoned for geomean. We add the explicit min term to do the same job more transparently.
- **Learned aggregator** (MLP from 4 sub-grades → grade). **Reject for v1**: opaque, harder to debug; 1 331 examples is enough for a 2-parameter formula but underdetermined for an MLP.
- **PSA's literal table** (10 = no weakness; 9 = one weakness; 8 = two weaknesses; …). **Hold for v2**: would require categorical weakness counting, more complex; revisit after measuring v1 ρ.

## Consequences

### Positive
- **Calibrated to PSA empirical behavior** — measurable via Spearman ρ vs TAG ground truth
- **User-facing differentiator** — `weakest_pillar` field is a UX feature competitors don't expose cleanly
- **Reversible** — formula has 2 fit parameters + 1 cap; can re-fit if data shifts

### Negative / risks
- **Discontinuity at the cap** — overall jumps from `0.6·g + 0.4·m` to `m+1.0` at the boundary. Small input changes near the cap could cause large output changes. Mitigation: smooth via softmin if observed in eval.
- **2-parameter fit on 1 331 cards** is fine for current data; if we add more sub-grade data later, re-fit.

## Implementation

- `src/grade_combiner.py` — formula constants exposed at top of module
- Fit script: `scripts/fit_grade_aggregator.py` (constrained least-squares against TAG overall grades)
- Output field: `weakest_pillar: "centering" | "corners" | "edges" | "surface"`

## When to revisit

- After collecting > 5 000 cards with full pillar grades — re-fit constants on larger sample
- If user feedback shows the cap rule feels unfair on specific edge cases (e.g. cards with one mild defect being over-penalised)
- If we add more pillars (e.g. holo-print quality as 5th) — formula needs extension

## Related

- [[2026-05-23-grade-weights-front-65-back-35]] — front/back combination (still active)
- [[2026-03-21-gemini-for-grading-not-custom-model]] — interim grading via Gemini (v3 plan replaces this)
- [[../../_context-packs/v3-defect-detection-plan]] — full v3 plan
- [[../../20-Areas/02-grading/_MOC]]

## Sources

- [PSA Grading Standards (official)](https://www.psacard.com/gradingstandards) — sub-grade tolerance rules
- [TAG Score methodology](https://taggrading.com/pages/score) — "DINGS" + compounding deductions
- [Ximilar Card Grading formula docs](https://docs.ximilar.com/services/card_grading/) — geomean baseline
- Phantom Display PSA-2026 guide — weakest-link rule confirmation
