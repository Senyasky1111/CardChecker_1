"""Orchestration for the /grade endpoint: bytes -> montages -> Claude grade -> contract.

Keeps src/api.py thin. Wires the validated grader (src/claude_grade) + the montage
builder (src/montage) + the confident empirical distribution (src/pregrade_distribution)
into the Decision-Card response contract from the TZ
(vault/10-Projects/2026-Q2-pregrading-integration.md).

Locked behavior (do not change without re-reading the context-pack):
- holistic grade ONLY for the grade; detector (detect_zones) is evidence/safety ONLY,
  never fed back into an LLM re-grade.
- distribution = empirical (pregrade_distribution), NOT the model's grade_distribution.
- both sides mandatory; the caller enforces that before calling here.
"""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import cv2
from PIL import Image, ImageFile

from src.montage import save_montage
from src.claude_grade import prep_full_card
from src import pregrade_distribution as pd

ImageFile.LOAD_TRUNCATED_IMAGES = True

# Detector severities we surface as evidence. MINOR over-flags (false-positives on gems)
# -> show only MODERATE+ (the validated reliable threshold).
EVIDENCE_SEVERITIES = ("MODERATE", "HEAVY")
BLUR_VAR_MIN = 60.0          # Laplacian variance below this => likely out of focus (needs phone-photo calibration)


def blur_score(img: "Image.Image") -> float:
    """Variance of Laplacian — higher = sharper. Cheap focus proxy for the photo-quality gate."""
    g = cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def quality_warnings(front_img, back_img) -> list[str]:
    """Advisory photo-quality checks (the phone-photo gate seed).

    NOTE: thresholds are provisional and MUST be calibrated on >=30 real phone photos
    before this becomes a hard 'retake' block (TZ Risks). For now it returns advisory
    strings; the frontend decides how strongly to surface them.
    """
    out = []
    for name, im in (("front", front_img), ("back", back_img)):
        if im is None:
            continue
        if blur_score(im) < BLUR_VAR_MIN:
            out.append(f"{name} photo looks soft/out of focus — retake sharper for an accurate grade")
    return out


def _write(tmp: str, name: str, data: bytes) -> str:
    p = os.path.join(tmp, name)
    with open(p, "wb") as f:
        f.write(data)
    return p


def build_assets(front_bytes: bytes, back_bytes: bytes, tmp: str, card_id: str = "card") -> dict:
    """Decode + crop + build the 8-zone montages and full-card crops for both sides.

    Returns paths {front_montage, back_montage, front_full, back_full} plus the decoded
    PIL images (for quality checks). Raises ValueError if an image can't be decoded.
    """
    fp = _write(tmp, "front.jpg", front_bytes)
    bp = _write(tmp, "back.jpg", back_bytes)
    try:
        front_img = Image.open(fp).convert("RGB")
        back_img = Image.open(bp).convert("RGB")
    except Exception as e:
        raise ValueError(f"could not decode image: {e}")

    fm = save_montage(front_img, card_id, "front", os.path.join(tmp, "front_montage.png"))
    bm = save_montage(back_img, card_id, "back", os.path.join(tmp, "back_montage.png"))
    ff = prep_full_card(fp, os.path.join(tmp, "front_full.png"))   # may return None on crop failure
    bf = prep_full_card(bp, os.path.join(tmp, "back_full.png"))
    return {"front_montage": fm, "back_montage": bm, "front_full": ff, "back_full": bf,
            "front_img": front_img, "back_img": back_img}


def _evidence(detections: dict, side: str) -> list[str]:
    """Worn zones at MODERATE+ for one side (the 'wear we found here' list)."""
    z = (detections or {}).get(side) or {}
    return [k for k, v in z.items() if v in EVIDENCE_SEVERITIES]


def _side_block(holistic: dict, detections: dict, side: str) -> dict | None:
    s = holistic.get(side)
    if not s:
        return None
    return {
        "grade": s.get("grade"),
        "centering": s.get("centering"),
        "corners": s.get("corners"),
        "edges": s.get("edges"),
        "surface": s.get("surface"),
        "worn_zones": _evidence(detections, side),   # detector evidence (MODERATE+), not the model's self-report
    }


def assemble(holistic: dict, detections: dict, warnings: list[str]) -> dict:
    """Build the Decision-Card response contract from grader + detector outputs."""
    front = holistic.get("front") or {}
    back = holistic.get("back")
    if back:
        overall = pd.build_overall(front_grade=front.get("grade"), back_grade=back.get("grade"))
    else:
        overall = pd.build_overall(raw_overall=holistic.get("overall_grade"))

    grade_it = overall["bucket"] in ("GEM", "MINT", "NM")   # confident action; card-value gate TODO
    return {
        "is_estimate": True,
        "footer": "Estimated condition from your photos — not an official PSA/BGS/CGC grade.",
        "overall": overall,
        "front": _side_block(holistic, detections, "front"),
        "back": _side_block(holistic, detections, "back"),
        "evidence": {"front": (detections or {}).get("front") or {},
                     "back": (detections or {}).get("back") or {}},
        "explanation": holistic.get("explanation", ""),
        "decision": "grade_it" if grade_it else "sell_raw",
        "quality_warnings": warnings,
        "_timing_ms": {"holistic": holistic.get("_ms"), "detect": detections.get("_ms")},
    }


def grade_card(grader, front_bytes: bytes, back_bytes: bytes, card_id: str = "card") -> dict:
    """Full pipeline. `grader` is a ready ClaudeGrader. Runs the holistic grade and the
    evidence detector CONCURRENTLY (2 sync API calls). Returns the response contract."""
    with tempfile.TemporaryDirectory(prefix="pregrade_") as tmp:
        assets = build_assets(front_bytes, back_bytes, tmp, card_id)
        warnings = quality_warnings(assets["front_img"], assets["back_img"])
        paths = dict(front_montage=assets["front_montage"], back_montage=assets["back_montage"],
                     front_full=assets["front_full"], back_full=assets["back_full"])
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_hol = ex.submit(grader.grade_montages, paths["front_montage"], paths["back_montage"],
                              paths["front_full"], paths["back_full"])
            f_det = ex.submit(grader.detect_zones, paths["front_montage"], paths["back_montage"],
                              paths["front_full"], paths["back_full"])
            holistic = f_hol.result()
            detections = f_det.result()
        return assemble(holistic, detections, warnings)
