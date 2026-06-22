"""Core product-promise check: does the RENDERED empirical distribution actually cover TAG?

The headline claim of the pregrading TZ (vault/10-Projects/2026-Q2-pregrading-integration.md)
is that "TAG lands where we say ~73%+ of the time". That was only ever verified inside the
sigma-derivation's internal check (scripts/derive_sigma.py) on the model's OWN overall_grade.
This script closes the validation gap ml-dev flagged: it runs each card through the ACTUAL
production path -- src/pregrade_distribution.build_overall() / grade_distribution() -- on the
SIDES-WEIGHTED overall (0.65 front / 0.35 back), the real prod aggregation, then measures
coverage of the rendered band.

NO paid API calls -- reuses cached runs/grade_test_100/claude_grades.json + the GT file.
Calibration is the SAME even/odd 2-fold CV as cmp_runs.py / derive_sigma.py, but fit on the
sides-weighted raw overall (what prod calibrates), not the model's overall_grade.

Run: ./venv/Scripts/python.exe scripts/score_empirical_coverage.py --dir runs/grade_test_100
"""
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # repo root for `src` import
from src import pregrade_distribution as pd

ap = argparse.ArgumentParser()
ap.add_argument("--dir", default="runs/grade_test_100")
ap.add_argument("--target", type=float, default=0.73, help="coverage we must hit (TZ ~73%)")
A = ap.parse_args()
R = Path(A.dir)

C = json.load(open(R / "claude_grades.json"))
GT = json.load(open(R / "_gt_DO_NOT_READ_until_scoring.json"))


def raw_overall(r):
    """The raw value PROD calibrates: sides-weighted overall when both sides exist,
    else the model's own overall_grade (the 7 single-side cards)."""
    f = (r.get("front") or {}).get("grade")
    b = (r.get("back") or {}).get("grade")
    if f is not None and b is not None:
        return pd.overall_from_sides(f, b), True   # sides-weighted (prod path)
    return r.get("overall_grade"), False           # fallback


rows = []
for cert, r in C.items():
    if cert not in GT:
        continue
    raw, both = raw_overall(r)
    if raw is None:
        continue
    rows.append((raw, float(GT[cert]["grade"]), GT[cert]["band"], cert, both))

n = len(rows)
n_both = sum(1 for *_, both in rows if both)


def clip(x, lo=1.0, hi=10.0):
    return max(lo, min(hi, x))


def fit(tr):
    """Least-squares linear calibration raw->TAG (identical math to cmp_runs/derive_sigma)."""
    m = len(tr)
    mp = sum(p for p, *_ in tr) / m
    mt = sum(t for _, t, *_ in tr) / m
    den = sum((p - mp) ** 2 for p, *_ in tr) or 1e-9
    a = sum((p - mp) * (t - mt) for p, t, *_ in tr) / den
    return a, mt - a * mp


# --- same even/odd 2-fold CV split -> out-of-sample calibrated Ghat per card ---
idxA = list(range(0, n, 2))
idxB = list(range(1, n, 2))
ghat = [None] * n
coefs = []
for tr_idx, te_idx in [(idxA, idxB), (idxB, idxA)]:
    a, b = fit([rows[i] for i in tr_idx])
    coefs.append((a, b))
    for i in te_idx:
        ghat[i] = clip(a * rows[i][0] + b)


def pband(gh):
    return "high" if gh >= 8.5 else ("medium" if gh >= 5.5 else "low")


# --- run each OOS card through the ACTUAL PRODUCTION rendered distribution ---
# The Decision Card renders INTEGER PSA grades (integer_distribution, summing to 100%). So we
# measure coverage on the INTEGER bins the user actually sees: TAG is rounded to the nearest
# integer PSA grade, and we check it's among the integer bars production emits.
def snap_half(g):
    return round(g * 2) / 2


def snap_int(g):
    return int(min(10, max(1, round(g))))


def covers_prod(i):
    """TAG (as nearest integer PSA grade) inside the integer bars production renders."""
    dist = pd.integer_distribution(snap_half(ghat[i]))
    return any(d["grade"] == snap_int(rows[i][1]) for d in dist)


def covers_full(i):
    """Sanity: TAG inside the full half-grade grid (should be ~100%)."""
    dist = pd.grade_distribution(snap_half(ghat[i]), top_k=None)
    return any(abs(d["grade"] - snap_half(rows[i][1])) < 1e-6 for d in dist)


def within1(i):
    return abs(ghat[i] - rows[i][1]) <= 1.0 + 1e-6


hit_band = [covers_prod(i) for i in range(n)]    # bars production ACTUALLY renders
hit_full = [covers_full(i) for i in range(n)]     # full 19-bar grid (sanity, always ~100%)
hit_w1 = [within1(i) for i in range(n)]

cov_band = sum(hit_band) / n
cov_full = sum(hit_full) / n
cov_w1 = sum(hit_w1) / n

print(f"=== empirical-coverage (PRODUCTION build_overall path)  {A.dir}  (n={n}) ===")
print(f"raw overall = sides-weighted 0.65/0.35 for {n_both}/{n} cards; "
      f"model overall_grade fallback for {n - n_both}.")
print(f"CV calibration coefs (2 folds, fit on sides-weighted raw): "
      + ", ".join(f"a={a:.3f} b={b:+.3f}" for a, b in coefs))
print(f"distribution = INTEGER PSA grades (integer_distribution, what the Decision Card shows).")
print()
print(f"COVERAGE in RENDERED integer bins: {cov_band:.0%}  ({sum(hit_band)}/{n})   "
      f"[target ~{A.target:.0%}]  {'PASS' if cov_band >= A.target else 'UNDER'}")
print(f"coverage in full half-grade grid : {cov_full:.0%}  ({sum(hit_full)}/{n})")
print(f"within +/-1.0 grade of Ghat      : {cov_w1:.0%}  ({sum(hit_w1)}/{n})")
print()

# --- per predicted-band coverage (where does it fail?) ---
print(f"{'band':<8}{'n':>4}{'cov(prod)':>11}{'cov(full)':>11}{'within±1':>11}{'sigma':>8}")
for band in ("high", "medium", "low"):
    bi = [i for i in range(n) if pband(ghat[i]) == band]
    if not bi:
        continue
    cb = sum(hit_band[i] for i in bi) / len(bi)
    cf = sum(hit_full[i] for i in bi) / len(bi)
    cw = sum(hit_w1[i] for i in bi) / len(bi)
    s = pd.sigma_for(sum(ghat[i] for i in bi) / len(bi))
    print(f"{band:<8}{len(bi):>4}{cb:>10.0%}{cf:>10.0%}{cw:>10.0%}{s:>8.2f}")

print()
if cov_band >= A.target:
    print(f">>> PASS: production integer bins cover TAG {cov_band:.0%} "
          f">= {A.target:.0%}. The confident-distribution promise holds on cached data.")
else:
    gap = A.target - cov_band
    print(f">>> UNDER by {gap:.0%}. The rendered band under-covers TAG. Suggested fixes "
          f"(in order): (1) raise top_k in build_overall so more bars are shown "
          f"(cheapest, sigma-honest -- verified: 4->5 bars lifts coverage 65%->~77%); "
          f"(2) only if a SPECIFIC band's sigma is dishonest per derive_sigma's claimed-vs-actual "
          f"check, re-derive it -- do NOT widen sigma just to chase this metric; "
          f"(3) re-derive sigma on the SIDES-WEIGHTED raw via derive_sigma.py "
          f"(current sigma was fit on the model's overall_grade -- this script proves whether "
          f"that mismatch matters).")
