"""Tests for src/pregrade_service contract assembly (no API calls).

Covers the response-contract glue: evidence filtered to MODERATE+, side blocks pull
detector evidence (not the model's self-report), overall uses the empirical distribution,
and the sell-vs-grade decision. The actual Claude calls are not exercised here.
"""
import pytest

from src.pregrade_service import assemble, _evidence, _side_block

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
    sb = _side_block(HOLISTIC, DET, "back")
    assert sorted(sb["worn_zones"]) == ["BL", "TR"]
    assert sb["grade"] == 6.5 and sb["surface"] == 7


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
