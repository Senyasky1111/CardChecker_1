"""CV-calibrated per-band MAE for a grade run (for A/B comparing input/prompt variants)."""
import argparse, json
from pathlib import Path
ap = argparse.ArgumentParser(); ap.add_argument("--dir", required=True); A = ap.parse_args()
R = Path(A.dir)
C = json.load(open(R / "claude_grades.json")); GT = json.load(open(R / "_gt_DO_NOT_READ_until_scoring.json"))
rows = [(C[c]["overall_grade"], float(GT[c]["grade"]), GT[c]["band"])
        for c in C if "overall_grade" in C[c] and c in GT]
def clip(x): return max(1.0, min(10.0, x))
def fit(tr):
    n = len(tr); mp = sum(p for p, _, _ in tr) / n; mt = sum(t for _, t, _ in tr) / n
    den = sum((p - mp) ** 2 for p, _, _ in tr) or 1e-9
    a = sum((p - mp) * (t - mt) for p, t, _ in tr) / den; return a, mt - a * mp
# 2-fold CV -> out-of-sample calibrated prediction per card (keyed by index)
idxA = list(range(0, len(rows), 2)); idxB = list(range(1, len(rows), 2))
pred = [None] * len(rows)
for tr_idx, te_idx in [(idxA, idxB), (idxB, idxA)]:
    a, b = fit([rows[i] for i in tr_idx])
    for i in te_idx:
        pred[i] = clip(a * rows[i][0] + b)
errs = [(abs(pred[i] - rows[i][1]), rows[i][2]) for i in range(len(rows))]
n = len(errs)
print(f"=== {A.dir}  (n={n}) ===")
print(f"  overall CV-cal MAE = {sum(e for e, _ in errs)/n:.2f}   within +/-1 = {100*sum(1 for e,_ in errs if e<=1)/n:.0f}%")
for bd in ("gem", "nm", "ex", "low"):
    bi = [i for i in range(len(rows)) if rows[i][2] == bd]
    if bi:
        cm = sum(errs[i][0] for i in bi) / len(bi)
        mp = sum(pred[i] for i in bi) / len(bi); mt = sum(rows[i][1] for i in bi) / len(bi)
        print(f"  band {bd:<4} n={len(bi):<3} calMAE={cm:.2f}  mean(cal)={mp:.1f} mean(TAG)={mt:.1f}")
