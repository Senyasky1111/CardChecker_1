"""The REAL GA success metric: 3-bucket decision accuracy + recall-on-PLAYED.

Not MAE. The locked decision metric (vault/_context-packs/claude-grader-experiments.md, Open
problems #5) is the coarse 3-class call -- GEM+/MID/PLAYED -- and a safety recall on PLAYED
(never miss a beat-up card by calling it mint). This collapses BOTH the calibrated Ghat and
TAG through src/pregrade_distribution.bucket() into 3 classes and reports the confusion matrix.

3-class mapping (from the 5 product buckets in pregrade_distribution.bucket()):
    GEM+   <- GEM (>=9.5) + MINT (9.0-9.5)        "grade it, top condition"
    MID    <- NM  (8.0-9.0) + EX (5.5-8.0)         "near-mint to excellent, judgement call"
    PLAYED <- PLAYED (<5.5)                         "sell raw / heavy wear" -- the safety class
Rationale: GEM/MINT is the high-value grade-it decision; PLAYED is the do-not-overclaim safety
floor; everything between is the ambiguous middle. recall-on-PLAYED = of cards TAG says PLAYED,
how many did we also call PLAYED (1 - overclaim rate).

NO paid API calls -- reuses cached runs/grade_test_100/claude_grades.json + GT.
Same even/odd 2-fold CV calibration as cmp_runs.py / derive_sigma.py, on the sides-weighted
overall (prod path), falling back to the model's overall_grade for single-side cards.

Run: ./venv/Scripts/python.exe scripts/score_buckets.py --dir runs/grade_test_100
"""
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # repo root for `src` import
from src import pregrade_distribution as pd

ap = argparse.ArgumentParser()
ap.add_argument("--dir", default="runs/grade_test_100")
A = ap.parse_args()
R = Path(A.dir)

C = json.load(open(R / "claude_grades.json"))
GT = json.load(open(R / "_gt_DO_NOT_READ_until_scoring.json"))

CLASSES = ["GEM+", "MID", "PLAYED"]


def coarse(grade):
    """Collapse the 5 product buckets into the 3 GA decision classes."""
    b = pd.bucket(grade)[0]            # GEM / MINT / NM / EX / PLAYED
    if b in ("GEM", "MINT"):
        return "GEM+"
    if b in ("NM", "EX"):
        return "MID"
    return "PLAYED"


def raw_overall(r):
    f = (r.get("front") or {}).get("grade")
    b = (r.get("back") or {}).get("grade")
    if f is not None and b is not None:
        return pd.overall_from_sides(f, b)
    return r.get("overall_grade")


rows = []
for cert, r in C.items():
    if cert not in GT:
        continue
    raw = raw_overall(r)
    if raw is None:
        continue
    rows.append((raw, float(GT[cert]["grade"])))

n = len(rows)


def clip(x, lo=1.0, hi=10.0):
    return max(lo, min(hi, x))


def fit(tr):
    m = len(tr)
    mp = sum(p for p, _ in tr) / m
    mt = sum(t for _, t in tr) / m
    den = sum((p - mp) ** 2 for p, _ in tr) or 1e-9
    a = sum((p - mp) * (t - mt) for p, t in tr) / den
    return a, mt - a * mp


# --- same even/odd 2-fold CV -> OOS calibrated Ghat per card ---
idxA = list(range(0, n, 2))
idxB = list(range(1, n, 2))
ghat = [None] * n
for tr_idx, te_idx in [(idxA, idxB), (idxB, idxA)]:
    a, b = fit([rows[i] for i in tr_idx])
    for i in te_idx:
        # snap to half-grade grid like build_overall does, so the bucket call matches prod
        ghat[i] = round(clip(a * rows[i][0] + b) * 2) / 2

pred_c = [coarse(ghat[i]) for i in range(n)]
tag_c = [coarse(rows[i][1]) for i in range(n)]

# --- 3x3 confusion matrix: rows = TAG (truth), cols = predicted ---
conf = {t: {p: 0 for p in CLASSES} for t in CLASSES}
for i in range(n):
    conf[tag_c[i]][pred_c[i]] += 1

exact = sum(1 for i in range(n) if pred_c[i] == tag_c[i]) / n

print(f"=== 3-bucket GA decision metric  {A.dir}  (n={n}) ===")
print("mapping: GEM+ = GEM|MINT (>=9.0) | MID = NM|EX (5.5-9.0) | PLAYED = <5.5\n")
print("confusion matrix  (rows = TAG truth, cols = predicted):")
hdr = "TAG\\pred " + "".join(f"{c:>9}" for c in CLASSES) + f"{'tot':>7}"
print(hdr)
for t in CLASSES:
    rowtot = sum(conf[t].values())
    line = f"{t:<9}" + "".join(f"{conf[t][p]:>9}" for p in CLASSES) + f"{rowtot:>7}"
    print(line)
coltot = {p: sum(conf[t][p] for t in CLASSES) for p in CLASSES}
print(f"{'tot':<9}" + "".join(f"{coltot[p]:>9}" for p in CLASSES) + f"{n:>7}")

print(f"\nEXACT 3-bucket agreement : {exact:.0%}  ({sum(1 for i in range(n) if pred_c[i]==tag_c[i])}/{n})")

# --- per-class precision/recall ---
print("\nper-class precision / recall:")
for c in CLASSES:
    tp = conf[c][c]
    fn = sum(conf[c][p] for p in CLASSES if p != c)      # TAG=c but predicted other
    fp = sum(conf[t][c] for t in CLASSES if t != c)      # predicted c but TAG other
    rec = tp / (tp + fn) if (tp + fn) else float("nan")
    prec = tp / (tp + fp) if (tp + fp) else float("nan")
    support = tp + fn
    print(f"  {c:<7} support={support:<3} precision={prec:.0%}  recall={rec:.0%}")

# --- the safety metric: recall on PLAYED + how badly misses overclaim ---
played_idx = [i for i in range(n) if tag_c[i] == "PLAYED"]
if played_idx:
    caught = sum(1 for i in played_idx if pred_c[i] == "PLAYED")
    called_gem = sum(1 for i in played_idx if pred_c[i] == "GEM+")
    print(f"\n>>> SAFETY: recall-on-PLAYED = {caught/len(played_idx):.0%}  "
          f"({caught}/{len(played_idx)} beat-up cards correctly NOT called mint).")
    if called_gem:
        print(f"    ⚠ {called_gem} PLAYED card(s) overclaimed as GEM+ "
              f"-- the dangerous error class; investigate these certs.")
    else:
        print(f"    no PLAYED card was overclaimed as GEM+ (worst-case error avoided).")
else:
    print("\n>>> SAFETY: no PLAYED cards in TAG for this set (the known degenerate-band issue).")
