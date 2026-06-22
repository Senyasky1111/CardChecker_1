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


INT_GRID = list(range(1, 11))   # 1 .. 10 -- PSA grades are integers


def integer_distribution(g_hat, round_pct=True):
    """Distribution over INTEGER PSA grades 1..10 (what the Decision Card renders).

    PSA grades are integers, so the displayed bars MUST be integers and sum to 100%.
    We take the full truncated-renormalized half-grade Gaussian and fold the half-grade
    mass into integers: an integer grade keeps its own mass; a .5 grade splits 50/50 to
    floor/ceil (clamped to [1,10], so 10.5 can't exist but 9.5 -> 9 & 10). Then renormalize
    and round to whole % with the top bar absorbing the residual (same helper behavior as
    grade_distribution), so it sums to exactly 1.0. Returns [{grade:int, prob}] high->low.
    """
    g_hat = clip(g_hat)
    s = sigma_for(g_hat)
    w = {g: math.exp(-((g - g_hat) ** 2) / (2 * s * s)) for g in HALF_GRID}
    z = sum(w.values()) or 1.0
    half = {g: w[g] / z for g in HALF_GRID}          # truncated+renormalized half-grade mass

    ints = {g: 0.0 for g in INT_GRID}
    for g, p in half.items():
        if float(g).is_integer():
            ints[int(g)] += p
        else:                                        # split .5 mass to neighbours, clamped to [1,10]
            lo = int(max(1, math.floor(g)))
            hi = int(min(10, math.ceil(g)))
            ints[lo] += p / 2
            ints[hi] += p / 2
    zi = sum(ints.values()) or 1.0
    ints = {g: p / zi for g, p in ints.items()}

    items = sorted(ints.items(), key=lambda kv: -kv[0])   # display order: high grade first
    if round_pct:
        pcts = [(g, round(p * 100)) for g, p in items if round(p * 100) > 0]
        drift = 100 - sum(p for _, p in pcts)
        if pcts and drift:                                # dump rounding residual on the top bar
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

    The headline grade = the model's own weighted overall (front*0.65 + back*0.35),
    NOT TAG-calibrated. STAKEHOLDER DECISION 2026-06-22: the `1.58*raw-4.88` TAG
    calibration was dragging the headline below the visible per-side sub-grades (e.g.
    sides 8/7.5 -> calibrated 7), which read as broken — TAG grades stricter than PSA in
    the mid range and we display a PSA-style scale. We now show the model's direct read so
    headline == weighted average of the side grades. (Trade-off: the model's raw scale is
    a bit compressed at the extremes — true gems read ~9 not 10; the real fix is a PSA
    recalibration on PSA-graded reference cards. `calibrate()` is kept for that future use.)
    Returns most_likely + bucket + label + confident empirical distribution.
    """
    if raw_overall is None:
        if front_grade is None or back_grade is None:
            raise ValueError("need raw_overall, or BOTH front_grade and back_grade")
        raw_overall = overall_from_sides(front_grade, back_grade)
    g_hat = clip(raw_overall)     # show the model's own grade (TAG calibration removed)
    # The rendered distribution is over INTEGER PSA grades and sums to 100% -- the frontend
    # renders integer rows only, so half-grade mass (8.5, 9.5, ...) must be folded into integers
    # or the bars visibly sum to ~52% (live-test bug, 2026-06-22). See integer_distribution().
    dist = integer_distribution(g_hat)
    most_likely = max(dist, key=lambda d: d["prob"])["grade"]   # integer mode = tallest bar
    # bucket/label derive from the integer headline so the word matches the number
    # (e.g. 8 -> "Near Mint", not "Excellent 8").
    b, label = bucket(most_likely)
    return {
        "most_likely": most_likely,
        "bucket": b,
        "label": label,
        "distribution": dist,
    }
