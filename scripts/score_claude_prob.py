"""Probabilistic + asymmetric-calibration scoring of Claude grades vs TAG.

Metrics:
  - point MAE (overall_grade)
  - E[grade] MAE (expected value of the grade_distribution)
  - coverage: fraction of cards where TAG grade falls in the predicted band (smallest
    contiguous grade set covering >=BAND_MASS probability)
  - asymmetric-calibrated MAE: fit a downward offset applied ONLY to cards the model
    judges DEFECTIVE (overall<CLEAN_THR or any worn_zone); clean cards untouched.
Usage: python scripts/score_claude_prob.py --dir runs/grade_test_100
"""
import argparse, json, math
from pathlib import Path

ap = argparse.ArgumentParser(); ap.add_argument("--dir", default="runs/grade_test_100")
ap.add_argument("--band-mass", type=float, default=0.8)
ap.add_argument("--clean-thr", type=float, default=8.5)
A = ap.parse_args()
R = Path(A.dir)
C = json.load(open(R / "claude_grades.json"))
GT = json.load(open(R / "_gt_DO_NOT_READ_until_scoring.json"))


def pear(a, b):
    if len(a) < 2:
        return 0
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = math.sqrt(sum((x - ma) ** 2 for x in a)); vb = math.sqrt(sum((y - mb) ** 2 for y in b))
    return cov / (va * vb) if va * vb else 0


def expected(dist):
    s = sum(d["prob"] for d in dist) or 1.0
    return sum(d["grade"] * d["prob"] for d in dist) / s


def band(dist, mass):
    """Smallest contiguous grade interval covering >= mass of probability."""
    ds = sorted(dist, key=lambda d: d["grade"]); s = sum(d["prob"] for d in ds) or 1.0
    ps = [(d["grade"], d["prob"] / s) for d in ds]
    best = None
    for i in range(len(ps)):
        acc = 0
        for j in range(i, len(ps)):
            acc += ps[j][1]
            if acc >= mass:
                lo, hi = ps[i][0], ps[j][0]
                if best is None or (hi - lo) < (best[1] - best[0]):
                    best = (lo, hi)
                break
    return best or (ps[0][0], ps[-1][0])


rows = []
for cert, r in C.items():
    if "overall_grade" not in r or cert not in GT:
        continue
    tag = float(GT[cert]["grade"])
    dist = r.get("grade_distribution") or [{"grade": r["overall_grade"], "prob": 1.0}]
    ev = expected(dist); lo, hi = band(dist, A.band_mass)
    worn = len(r["front"]["worn_zones"]) + (len(r["back"]["worn_zones"]) if r["back"] else 0)
    defective = r["overall_grade"] < A.clean_thr or worn > 0
    rows.append(dict(cert=cert, tag=tag, pt=r["overall_grade"], ev=ev, lo=lo, hi=hi,
                     defective=defective, band=GT[cert]["band"]))

n = len(rows)
pt_mae = sum(abs(x["pt"] - x["tag"]) for x in rows) / n
ev_mae = sum(abs(x["ev"] - x["tag"]) for x in rows) / n
cov = sum(1 for x in rows if x["lo"] - 1e-6 <= x["tag"] <= x["hi"] + 1e-6) / n
avg_bw = sum(x["hi"] - x["lo"] for x in rows) / n

# fit asymmetric offset on DEFECTIVE cards only (clean untouched)
defs = [x for x in rows if x["defective"]]
delta = (sum(x["pt"] - x["tag"] for x in defs) / len(defs)) if defs else 0.0
def cal(x):
    return x["pt"] - (delta if x["defective"] else 0.0)
cal_mae = sum(abs(cal(x) - x["tag"]) for x in rows) / n

print(f"=== {A.dir}  (n={n}) ===")
print(f"point   MAE={pt_mae:.2f}  r={pear([x['pt'] for x in rows],[x['tag'] for x in rows]):.3f}")
print(f"E[grade]MAE={ev_mae:.2f}  r={pear([x['ev'] for x in rows],[x['tag'] for x in rows]):.3f}")
print(f"BAND coverage @{int(A.band_mass*100)}%: {100*cov:.0f}% of cards have TAG inside predicted range  (avg width {avg_bw:.2f})")
print(f"ASYMMETRIC calibration: subtract {delta:+.2f} from DEFECTIVE cards only ({len(defs)}/{n}); clean untouched")
print(f"  -> calibrated MAE={cal_mae:.2f}  (was {pt_mae:.2f})")
print(f"  within +/-1.0: {100*sum(1 for x in rows if abs(cal(x)-x['tag'])<=1)/n:.0f}%   +/-1.5: {100*sum(1 for x in rows if abs(cal(x)-x['tag'])<=1.5)/n:.0f}%")
# per-band point vs tag
for b in ("gem", "nm", "ex", "low"):
    bb = [x for x in rows if x["band"] == b]
    if bb:
        print(f"  band {b:<4} n={len(bb):<3} mean(pt)={sum(x['pt'] for x in bb)/len(bb):.1f} mean(TAG)={sum(x['tag'] for x in bb)/len(bb):.1f} mean(cal)={sum(cal(x) for x in bb)/len(bb):.1f}")
