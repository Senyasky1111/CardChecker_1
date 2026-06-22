"""Unit tests for src/pregrade_distribution -- calibration + empirical distribution.

Covers the highest-bug-risk pure math of the /grade endpoint (TZ B1/B1b):
probs sum to 1, truncation at [1,10] + renormalize, calibration clamps both ends,
sigma-band selection, bucket boundaries, side weighting, confident-voice invariants.
"""
import math
import pytest

from src.pregrade_distribution import (
    calibrate, overall_from_sides, band_for, sigma_for,
    grade_distribution, integer_distribution, bucket, build_overall, SIGMA, SIGMA_FLOOR,
)


# --- calibration ---
def test_calibrate_clamps_both_ends():
    assert calibrate(10.0) == 10.0          # 1.58*10-4.88=10.92 -> clip 10
    assert calibrate(0.0) == 1.0            # negative -> clip 1
    assert calibrate(3.8) == pytest.approx(1.124, abs=1e-3)


def test_calibrate_pushes_gems_up_compresses_low():
    # raw model compresses the scale; calibration should spread it back out
    assert calibrate(8.9) > 8.9            # gem pushed up
    assert calibrate(6.6) < 6.6            # beat-up pushed down


# --- side weighting ---
def test_overall_weighting():
    assert overall_from_sides(10, 0) == pytest.approx(6.5)
    assert overall_from_sides(8, 8) == pytest.approx(8.0)


# --- band + sigma selection ---
@pytest.mark.parametrize("g,b", [(10, "high"), (8.5, "high"),
                                 (8.4, "medium"), (5.5, "medium"),
                                 (5.4, "low"), (1.0, "low")])
def test_band_boundaries(g, b):
    assert band_for(g) == b


def test_sigma_lookup_and_floor():
    assert sigma_for(9.0) == SIGMA["high"]
    assert sigma_for(7.0) == SIGMA["medium"]
    # low band is sparse -> floored at the overall sigma
    assert sigma_for(3.0) == max(SIGMA["low"], SIGMA_FLOOR)


# --- distribution invariants ---
@pytest.mark.parametrize("g", [1.0, 3.6, 5.5, 6.4, 8.5, 9.3, 10.0])
def test_distribution_probs_sum_to_one(g):
    for tk in (None, 4):
        d = grade_distribution(g, top_k=tk)
        assert sum(x["prob"] for x in d) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize("g", [1.0, 5.0, 9.3, 10.0])
def test_distribution_grades_in_range(g):
    d = grade_distribution(g, top_k=None)
    assert all(1.0 <= x["grade"] <= 10.0 for x in d)


def test_distribution_truncates_and_renormalizes_at_ceiling():
    # Ghat near 10 must not leak mass above 10; full grid still sums to 1
    d = grade_distribution(9.7, top_k=None)
    assert max(x["grade"] for x in d) == 10.0
    assert sum(x["prob"] for x in d) == pytest.approx(1.0, abs=1e-6)


def test_distribution_sorted_high_to_low():
    d = grade_distribution(7.0, top_k=4)
    grades = [x["grade"] for x in d]
    assert grades == sorted(grades, reverse=True)


def test_distribution_peaks_near_point_estimate():
    d = grade_distribution(6.0, top_k=None)
    top = max(d, key=lambda x: x["prob"])
    assert abs(top["grade"] - 6.0) <= 0.5


def test_medium_band_is_wider_than_high():
    # honest uncertainty: a medium card's top bar must be less peaked than a gem's
    gem_top = max(x["prob"] for x in grade_distribution(9.5, top_k=None))
    mid_top = max(x["prob"] for x in grade_distribution(6.5, top_k=None))
    assert mid_top < gem_top


# --- buckets ---
@pytest.mark.parametrize("g,b", [
    (10.0, "GEM"), (9.5, "GEM"), (9.4, "MINT"), (9.0, "MINT"),
    (8.9, "NM"), (8.0, "NM"), (7.9, "EX"), (5.5, "EX"), (5.4, "PLAYED"), (1.0, "PLAYED"),
])
def test_bucket_boundaries(g, b):
    assert bucket(g)[0] == b


# --- end-to-end overall block ---
def test_build_overall_from_sides_matches_raw():
    raw = overall_from_sides(9.0, 8.5)
    a = build_overall(raw_overall=raw)
    b = build_overall(front_grade=9.0, back_grade=8.5)
    assert a == b


def test_build_overall_requires_both_sides():
    with pytest.raises(ValueError):
        build_overall(front_grade=9.0)        # back missing -> reject


def test_build_overall_shape_and_confident_voice():
    o = build_overall(front_grade=6.5, back_grade=6.0)
    assert set(o) == {"most_likely", "bucket", "label", "distribution"}
    # most_likely is now the INTEGER mode (PSA grades are integers; matches the tallest bar)
    assert isinstance(o["most_likely"], int)
    assert sum(x["prob"] for x in o["distribution"]) == pytest.approx(1.0, abs=1e-6)
    # confident voice: no apologetic confidence/uncertainty fields leak into the block
    assert "confidence" not in o and "low_confidence" not in o


# --- integer-binned distribution (what the Decision Card renders; PSA grades are integers) ---
@pytest.mark.parametrize("g", [1.0, 3.0, 5.5, 6.4, 8.5, 9.0, 9.7, 10.0])
def test_integer_distribution_grades_are_integers(g):
    d = integer_distribution(g)
    assert all(isinstance(x["grade"], int) for x in d)
    assert all(1 <= x["grade"] <= 10 for x in d)


@pytest.mark.parametrize("g", [1.0, 3.0, 5.5, 6.4, 8.5, 9.0, 9.7, 10.0])
def test_integer_distribution_sums_to_one(g):
    d = integer_distribution(g)
    assert sum(x["prob"] for x in d) == pytest.approx(1.0, abs=1e-9)   # must show 100%, not 52%


def test_integer_distribution_no_half_grade_mass_dropped():
    # the live bug: half-grade bars (8.5, 9.5) silently vanished -> sum 52%. Now folded in.
    d = integer_distribution(9.0)
    assert sum(x["prob"] for x in d) == pytest.approx(1.0, abs=1e-9)
    assert {x["grade"] for x in d} <= set(range(1, 11))


def test_integer_distribution_peaks_near_point_estimate():
    d = integer_distribution(9.0)
    top = max(d, key=lambda x: x["prob"])
    assert abs(top["grade"] - 9) <= 1


def test_build_overall_most_likely_matches_tallest_bar():
    o = build_overall(front_grade=9.0, back_grade=8.5)
    tallest = max(o["distribution"], key=lambda x: x["prob"])["grade"]
    assert o["most_likely"] == tallest
