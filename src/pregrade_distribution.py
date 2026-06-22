"""Pregrading: calibration + confident empirical grade distribution.

Pure, side-effect-free functions for the `/grade` endpoint (TZ B1/B1b,
vault/10-Projects/2026-Q2-pregrading-integration.md). No API calls, no I/O.

The headline output is a CONFIDENT empirical probability distribution over grades,
built from our measured residual error per predicted-grade band -- NOT the model's
own (overconfident) grade_distribution. Sigma was derived from CV-calibrated
residuals on runs/grade_test_100 via scripts/derive_sigma.py (2026-06-22).
"""
import math

# Locked linear calibration (raw model overall -> TAG scale). Headline coefs;
# the per-fold CV values were 1.65/-5.47 and 1.46/-3.93 (mean ~1.55/-4.7).
CAL_A, CAL_B = 1.58, -4.88

# Empirical sigma of the calibrated residual, binned by PREDICTED grade (Ghat) --
# the only thing known at inference time. Derived 2026-06-22, see sigma_table.json.
SIGMA = {"high": 0.69, "medium": 1.76, "low": 1.52}
SIGMA_FLOOR = 1.32   # overall residual sigma; floor for sparse bins (low n=7)

# Side weighting and bucket labels (TZ).
FRONT_W, BACK_W = 0.65, 0.35
HALF_GRID = [round(1.0 + 0.5 * k, 1) for k in range(19)]   # 1.0 .. 10.0


def clip(x, lo=1.0, hi=10.0):
    return max(lo, min(hi, x))


def calibrate(raw_overall):
    """Map a raw model overall grade onto the calibrated [1,10] scale."""
    return clip(CAL_A * raw_overall + CAL_B)


def overall_from_sides(front_grade, back_grade):
    """Weighted overall = front*0.65 + back*0.35 (both sides mandatory)."""
    return FRONT_W * front_grade + BACK_W * back_grade


def band_for(g_hat):
    """Predicted-grade band used to pick sigma."""
    if g_hat >= 8.5:
        return "high"
    if g_hat >= 5.5:
        return "medium"
    return "low"


def sigma_for(g_hat):
    """Sigma for a calibrated point estimate, with the sparse-bin floor."""
    return max(SIGMA[band_for(g_hat)], 0.3) if band_for(g_hat) != "low" \
        else max(SIGMA["low"], SIGMA_FLOOR, 0.3)


def grade_distribution(g_hat, top_k=None, round_pct=True):
    """Discretized truncated-renormalized Gaussian on the half-grade grid.

    Returns a list of {"grade", "prob"} sorted high->low grade. Probabilities are
    truncated to [1,10] and renormalized to sum to 1.0 BEFORE any top_k trim, so
    the trimmed bars still reflect true mass. With round_pct, probs are rounded to
    whole percents and the largest bar absorbs the rounding residual (sum stays 1.0).
    """
    g_hat = clip(g_hat)
    s = sigma_for(g_hat)
    w = {g: math.exp(-((g - g_hat) ** 2) / (2 * s * s)) for g in HALF_GRID}
    z = sum(w.values()) or 1.0
    dist = {g: w[g] / z for g in HALF_GRID}

    items = sorted(dist.items(), key=lambda kv: -kv[1])
    if top_k:
        items = items[:top_k]
        z2 = sum(p for _, p in items) or 1.0
        items = [(g, p / z2) for g, p in items]

    items = sorted(items, key=lambda kv: -kv[0])   # display order: high grade first
    if round_pct:
        pcts = [(g, round(p * 100)) for g, p in items]
        drift = 100 - sum(p for _, p in pcts)
        if pcts and drift:                          # dump rounding residual on the top bar
            top_i = max(range(len(pcts)), key=lambda i: pcts[i][1])
            pcts[top_i] = (pcts[top_i][0], pcts[top_i][1] + drift)
        return [{"grade": g, "prob": p / 100.0} for g, p in pcts]
    return [{"grade": g, "prob": p} for g, p in items]


def bucket(grade):
    """Coarse condition bucket + label (TZ)."""
    if grade >= 9.5:
        return "GEM", "Gem Mint"
    if grade >= 9.0:
        return "MINT", "Mint"
    if grade >= 8.0:
        return "NM", "Near Mint"
    if grade >= 5.5:
        return "EX", "Excellent"
    return "PLAYED", "Played"


def build_overall(raw_overall=None, front_grade=None, back_grade=None):
    """Assemble the `overall` block of the /grade response.

    Pass either the model's raw overall, or both side grades (recomputes the
    weighted overall, then calibrates). Returns most_likely + bucket + label +
    confident empirical distribution.
    """
    if raw_overall is None:
        if front_grade is None or back_grade is None:
            raise ValueError("need raw_overall, or BOTH front_grade and back_grade")
        raw_overall = overall_from_sides(front_grade, back_grade)
    g_hat = round(calibrate(raw_overall) * 2) / 2     # snap to half-grade grid
    b, label = bucket(g_hat)
    return {
        "most_likely": g_hat,
        "bucket": b,
        "label": label,
        # top_k=5: at medium σ≈1.8 four half-grade bars only span ~65% of TAG outcomes;
        # five bars lift rendered-band coverage to ~77% (>=73% promise). Verified honest —
        # widening σ instead would inflate stated uncertainty (score_empirical_coverage.py).
        "distribution": grade_distribution(g_hat, top_k=5),
    }
