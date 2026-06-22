"""Tests for src/pregrade_service contract assembly (no API calls).

Covers the response-contract glue: evidence filtered to MODERATE+, side blocks pull
detector evidence (not the model's self-report), overall uses the empirical distribution,
and the sell-vs-grade decision. The actual Claude calls are not exercised here.
"""
import pytest

from src.pregrade_service import assemble, _evidence, _side_block, _safety_floor

HOLISTIC = {
    "front": {"grade": 7.5, "centering": 8, "corners": 7, "edges": 7, "surface": 8.5, "worn_zones": ["LEFT"]},
    "back": {"grade": 6.5, "centering": 8, "corners": 6, "edges": 6.5, "surface": 7, "worn_zones": ["TR"]},
    "overall_grade": 7.2, "explanation": "Light edge whitening on back.", "_ms": 9000,
}
DET = {
    "front": {"TL": "CLEAN", "TR": "CLEAN", "BL": "CLEAN", "BR": "CLEAN",
              "TOP": "MINOR", "BOTTOM": "CLEAN", "LEFT": "MODERATE", "RIGHT": "CLEAN"},
    "back": {"TL": "CLEAN", "TR": "MODERATE", "BL": "HEAVY", "BR": "CLEAN",
             "TOP": "CLEAN", "BOTTOM": "MINOR", "LEFT": "CLEAN", "RIGHT": "CLEAN"},
    "_ms": 4000,
}


def test_evidence_filters_to_moderate_plus():
    # MINOR and CLEAN dropped; MODERATE + HEAVY kept
    assert _evidence(DET, "front") == ["LEFT"]
    assert sorted(_evidence(DET, "back")) == ["BL", "TR"]


def test_side_block_uses_detector_not_model_worn_zones():
    # holistic.back.worn_zones is ['TR'] but the detector found TR+BL at MODERATE+
    worn = _evidence(DET, "back")
    sb = _side_block(HOLISTIC, "back", 6.5, HOLISTIC["back"]["centering"], worn)
    assert sorted(sb["worn_zones"]) == ["BL", "TR"]
    assert sb["grade"] == 6.5 and sb["surface"] == 7


def test_safety_floor_one_way():
    # high grade + many heavy zones -> capped at 5.0
    assert _safety_floor(8.5, 6) == (5.0, True)
    assert _safety_floor(8.5, 7) == (5.0, True)
    # below the zone count -> untouched
    assert _safety_floor(8.5, 5) == (8.5, False)
    # already low -> never raised
    assert _safety_floor(4.0, 8) == (4.0, False)
    # None grade -> passthrough
    assert _safety_floor(None, 8) == (None, False)


def test_assemble_applies_safety_floor_to_high_grade_worn_side():
    # front graded 7.5 by the model but the detector flags 6 MODERATE+ zones -> floored to 5.0
    det = {
        "front": {"TL": "MODERATE", "TR": "MODERATE", "BL": "MODERATE", "BR": "HEAVY",
                  "TOP": "MODERATE", "BOTTOM": "HEAVY", "LEFT": "CLEAN", "RIGHT": "CLEAN"},
        "back": {z: "CLEAN" for z in ("TL", "TR", "BL", "BR", "TOP", "BOTTOM", "LEFT", "RIGHT")},
        "_ms": 1,
    }
    r = assemble(HOLISTIC, det, [])
    assert r["front"]["grade"] == 5.0          # capped by the safety floor
    assert r["safety_floor"]["front"] is True
    assert r["safety_floor"]["back"] is False
    assert r["back"]["grade"] == 6.0           # weakest-link of back pillars (corners 6), untouched by floor


def test_weakest_link_caps_on_worst_subgrade():
    import src.pregrade_distribution as pd
    assert pd.weakest_link([10, 10, 10, 4]) == 5.0     # one bad attribute caps it (not 8/avg)
    assert pd.weakest_link([10, 8, 8, 8.5]) == 8.0     # lowest is 8 -> 8
    assert pd.weakest_link([9, 9, 9, 9]) == 9.0
    assert pd.weakest_link([None, 8, 7, 9]) == 7.5     # None ignored; +0.5 bump (others avg 1.5 higher)


def test_centering_grade_from_offset_table():
    import src.pregrade_distribution as pd
    assert pd.centering_grade_from_offset(4) == 10     # 46/54
    assert pd.centering_grade_from_offset(8) == 9      # 58/42
    assert pd.centering_grade_from_offset(15) == 7
    assert pd.centering_grade_from_offset(None) is None


def test_assemble_uses_geometry_centering_and_front_primary():
    # front pillars strong (8/8/8.5) + measured centering 10; back slightly worse + centering 9
    hol = {"front": {"corners": 8, "edges": 8, "surface": 8.5},
           "back": {"corners": 7.5, "edges": 8, "surface": 8}, "overall_grade": 7.8, "_ms": 1}
    r = assemble(hol, {"front": {}, "back": {}, "_ms": 1}, [],
                 front_centering_off=4, back_centering_off=8)
    assert r["front"]["centering"] == 10 and r["back"]["centering"] == 9   # from geometry, not grader
    assert r["front"]["grade"] == 8.0                                       # weakest-link of front
    # front-primary: back 7.5 doesn't drag a strong front to a tie -> overall reads 8
    assert r["overall"]["most_likely"] == 8


def test_assemble_front_defect_harsher_than_back_defect():
    # a corner-4 on the FRONT caps harder than the same on the back
    front4 = assemble({"front": {"corners": 4, "edges": 10, "surface": 10},
                       "back": {"corners": 10, "edges": 10, "surface": 10}, "_ms": 1},
                      {"front": {}, "back": {}, "_ms": 1}, [], front_centering_off=3, back_centering_off=3)
    back4 = assemble({"front": {"corners": 10, "edges": 10, "surface": 10},
                      "back": {"corners": 4, "edges": 10, "surface": 10}, "_ms": 1},
                     {"front": {}, "back": {}, "_ms": 1}, [], front_centering_off=3, back_centering_off=3)
    assert front4["overall"]["most_likely"] < back4["overall"]["most_likely"]


def test_assemble_contract_shape_and_distribution():
    r = assemble(HOLISTIC, DET, [])
    assert set(r) >= {"is_estimate", "footer", "overall", "front", "back",
                      "evidence", "explanation", "decision", "quality_warnings"}
    assert r["is_estimate"] is True
    o = r["overall"]
    assert set(o) == {"most_likely", "bucket", "label", "distribution"}
    assert sum(x["prob"] for x in o["distribution"]) == pytest.approx(1.0, abs=1e-6)
    # confident voice: no apologetic confidence field anywhere in overall
    assert "confidence" not in o


def test_assemble_decision_sell_vs_grade():
    # EX bucket -> sell_raw
    assert assemble(HOLISTIC, DET, [])["decision"] == "sell_raw"
    # a clean gem -> grade_it
    gem = {"front": {"grade": 10, "centering": 10, "corners": 10, "edges": 10, "surface": 10, "worn_zones": []},
           "back": {"grade": 9.5, "centering": 10, "corners": 9.5, "edges": 9.5, "surface": 10, "worn_zones": []},
           "overall_grade": 9.8, "explanation": "Pristine.", "_ms": 1}
    clean = {"front": {z: "CLEAN" for z in ("TL", "TR", "BL", "BR", "TOP", "BOTTOM", "LEFT", "RIGHT")},
             "back": {z: "CLEAN" for z in ("TL", "TR", "BL", "BR", "TOP", "BOTTOM", "LEFT", "RIGHT")}, "_ms": 1}
    assert assemble(gem, clean, [])["decision"] == "grade_it"


def test_assemble_back_missing_falls_back_to_overall():
    h = {"front": {"grade": 8, "centering": 8, "corners": 8, "edges": 8, "surface": 8, "worn_zones": []},
         "back": None, "overall_grade": 8.0, "explanation": "", "_ms": 1}
    r = assemble(h, {"front": {}, "back": None}, [])
    assert r["back"] is None
    assert sum(x["prob"] for x in r["overall"]["distribution"]) == pytest.approx(1.0, abs=1e-6)
