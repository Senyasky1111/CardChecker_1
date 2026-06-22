"""Empirically derive the per-band sigma for the pregrading distribution.

Closes blocker #2 of the pregrading integration: the TZ placeholders 0.9/1.1/1.8
were per-band MAE reused as if they were Gaussian std. Here we fit the REAL sigma
from CV-calibrated residuals, binned by PREDICTED grade (Ĝ) -- which is all we know
at inference time -- then verify coverage (empirical vs normal-implied).

Run: ./venv/Scripts/python.exe scripts/derive_sigma.py --dir runs/grade_test_100
"""
import argparse, json, math
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--dir", default="runs/grade_test_100")
ap.add_argument("--out", default=None, help="optional JSON dump of the sigma table + distributions")
A = ap.parse_args()
R = Path(A.dir)

C = json.load(open(R / "claude_grades.json"))
GT = json.load(open(R / "_gt_DO_NOT_READ_until_scoring.json"))
rows = [(C[c]["overall_grade"], float(GT[c]["grade"]), GT[c]["band"], c)
        for c in C if "overall_grade" in C[c] and c in GT]


def clip(x, lo=1.0, hi=10.0):
    return max(lo, min(hi, x))


def fit(tr):
    """Least-squares linear calibration raw->TAG (identical to cmp_runs.py)."""
    n = len(tr)
    mp = sum(p for p, _, _, _ in tr) / n
    mt = sum(t for _, t, _, _ in tr) / n
    den = sum((p - mp) ** 2 for p, _, _, _ in tr) or 1e-9
    a = sum((p - mp) * (t - mt) for p, t, _, _ in tr) / den
    return a, mt - a * mp


# --- 2-fold CV -> out-of-sample calibrated prediction per card (same split as cmp_runs) ---
idxA = list(range(0, len(rows), 2))
idxB = list(range(1, len(rows), 2))
pred = [None] * len(rows)
coefs = []
for tr_idx, te_idx in [(idxA, idxB), (idxB, idxA)]:
    a, b = fit([rows[i] for i in tr_idx])
    coefs.append((a, b))
    for i in te_idx:
        pred[i] = clip(a * rows[i][0] + b)

resid = [pred[i] - rows[i][1] for i in range(len(rows))]   # calibrated_pred - TAG
n = len(rows)
overall_mae = sum(abs(r) for r in resid) / n
print(f"=== {A.dir}  (n={n}) ===")
print(f"CV calibration coefs (2 folds): "
      + ", ".join(f"a={a:.3f} b={b:+.3f}" for a, b in coefs))
print(f"overall CV-cal MAE = {overall_mae:.2f}   "
      f"within +/-1 = {100*sum(1 for r in resid if abs(r)<=1)/n:.0f}%   "
      f"within +/-2 = {100*sum(1 for r in resid if abs(r)<=2)/n:.0f}%\n")


def std(xs):
    if len(xs) < 2:
        return float("nan")
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def norm_cov(sigma, k):
    """P(|N(0,sigma)| <= k) -- normal-implied coverage within +/-k."""
    if sigma <= 1e-9:
        return 1.0
    return math.erf(k / (sigma * math.sqrt(2)))


# --- Bin by PREDICTED Ĝ (inference-time knowledge), 3 product-aligned bands ---
def gband(gh):
    if gh >= 8.5:
        return "high"
    if gh >= 5.5:
        return "medium"
    return "low"


print("--- sigma binned by PREDICTED Ĝ (this is the inference-time lookup) ---")
print(f"{'band':<8}{'Ĝ range':<12}{'n':>4}{'sigma':>8}{'bias':>8}"
      f"{'emp±1':>8}{'norm±1':>8}{'emp±2':>8}{'norm±2':>8}")
sigma_table = {}
for band, rng in [("high", "Ĝ≥8.5"), ("medium", "5.5–8.5"), ("low", "Ĝ<5.5")]:
    bi = [i for i in range(n) if gband(pred[i]) == band]
    if not bi:
        continue
    rs = [resid[i] for i in bi]
    s = std(rs)
    bias = sum(rs) / len(rs)
    emp1 = sum(1 for i in bi if abs(resid[i]) <= 1) / len(bi)
    emp2 = sum(1 for i in bi if abs(resid[i]) <= 2) / len(bi)
    sigma_table[band] = round(s, 2)
    print(f"{band:<8}{rng:<12}{len(bi):>4}{s:>8.2f}{bias:>+8.2f}"
          f"{emp1:>8.0%}{norm_cov(s,1):>8.0%}{emp2:>8.0%}{norm_cov(s,2):>8.0%}")

# Pool guard: if a band has <8 samples, fall back to the overall sigma
overall_sigma = std(resid)
print(f"\noverall residual sigma = {overall_sigma:.2f}  (fallback for sparse bins)")
for band in ("high", "medium", "low"):
    bi = [i for i in range(n) if gband(pred[i]) == band]
    if 0 < len(bi) < 8:
        print(f"  ⚠ band {band} has only {len(bi)} samples -> pool toward overall sigma")

# --- For reference: sigma binned by TAG band (NOT usable at inference, sanity only) ---
print("\n--- (reference only) residual sigma binned by TAG band ---")
for bd in ("gem", "nm", "ex", "low"):
    bi = [i for i in range(n) if rows[i][2] == bd]
    if bi:
        s = std([resid[i] for i in bi])
        mae = sum(abs(resid[i]) for i in bi) / len(bi)
        print(f"  TAG {bd:<4} n={len(bi):<3} sigma={s:.2f}  MAE={mae:.2f}  "
              f"(note: sigma != MAE -- this is the TZ placeholder bug)")


# --- Build + verify the discretized truncated-renormalized distribution ---
HALF = [round(1 + 0.5 * k, 1) for k in range(0, 19)]   # 1.0 .. 10.0 half-steps


def distribution(g_hat, sigma):
    """Discretized Gaussian on the half-grade grid, truncated to [1,10], renormalized."""
    w = {g: math.exp(-((g - g_hat) ** 2) / (2 * sigma * sigma)) for g in HALF}
    z = sum(w.values()) or 1.0
    return {g: w[g] / z for g in HALF}


# Calibration check: does the distribution's claimed P(|TAG-Ĝ|<=1) match reality per band?
print("\n--- distribution calibration check (claimed vs actual P(TAG within ±1)) ---")
for band in ("high", "medium", "low"):
    bi = [i for i in range(n) if gband(pred[i]) == band]
    if not bi or band not in sigma_table:
        continue
    s = max(sigma_table[band], 0.3)
    claimed = []
    actual = []
    for i in bi:
        d = distribution(pred[i], s)
        lo, hi = pred[i] - 1.0, pred[i] + 1.0
        claimed.append(sum(p for g, p in d.items() if lo - 1e-6 <= g <= hi + 1e-6))
        actual.append(1 if abs(resid[i]) <= 1 else 0)
    print(f"  {band:<8} claimed≈{sum(claimed)/len(claimed):.0%}   "
          f"actual={sum(actual)/len(actual):.0%}   (match => sigma honest)")

# Example rendered distributions (what the user sees)
print("\n--- example rendered distributions (top-4 grades) ---")
for g_hat, band in [(9.3, "high"), (6.4, "medium"), (3.6, "low")]:
    s = max(sigma_table.get(band, overall_sigma), 0.3)
    d = distribution(g_hat, s)
    top = sorted(d.items(), key=lambda kv: -kv[1])[:4]
    top = sorted(top, key=lambda kv: -kv[0])
    txt = "  ".join(f"{g:g}:{p:.0%}" for g, p in top)
    print(f"  Ĝ={g_hat} ({band}, σ={s:.2f}) -> {txt}")

print("\n>>> SIGMA TABLE TO LOCK:", json.dumps(sigma_table), "(fallback", round(overall_sigma, 2), ")")

if A.out:
    json.dump({
        "sigma_by_predicted_band": sigma_table,
        "overall_sigma": round(overall_sigma, 2),
        "cv_coefs": coefs,
        "overall_cal_mae": round(overall_mae, 3),
        "bands": {"high": "Ĝ>=8.5", "medium": "5.5<=Ĝ<8.5", "low": "Ĝ<5.5"},
    }, open(A.out, "w"), indent=2)
    print(f"\nwrote {A.out}")
