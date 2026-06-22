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

import hashlib

from src.montage import save_montage, zone_crops
from src.claude_grade import prep_full_card
from src import pregrade_distribution as pd

ImageFile.LOAD_TRUNCATED_IMAGES = True

# Detector severities we surface as evidence. MINOR over-flags (false-positives on gems)
# -> show only MODERATE+ (the validated reliable threshold).
EVIDENCE_SEVERITIES = ("MODERATE", "HEAVY")
BLUR_VAR_MIN = 60.0          # Laplacian variance below this => likely out of focus (needs phone-photo calibration)

# Deterministic one-way safety floor (TZ B2): a side with this many MODERATE+ zones
# cannot read as a high grade. Only ever LOWERS a side grade, never raises it.
SAFETY_FLOOR_ZONE_COUNT = 6
SAFETY_FLOOR_CAP = 5.0

# PSA/BGS weight the FRONT more than the back: a back flaw lowers the card less than the same
# flaw on the front. We give the back ~1 grade of leniency when it caps the overall (but a
# truly bad back, e.g. a 4, still drags the card down — leniency just softens it by one band).
BACK_LENIENCY = 1.0


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


def _safety_floor(grade, worn_count: int) -> tuple:
    """One-way cap (TZ B2): a side with >=SAFETY_FLOOR_ZONE_COUNT MODERATE+ zones can't
    read as high grade. Returns (possibly-capped grade, applied?). Never raises a grade."""
    if grade is None:
        return grade, False
    if worn_count >= SAFETY_FLOOR_ZONE_COUNT and float(grade) > SAFETY_FLOOR_CAP:
        return SAFETY_FLOOR_CAP, True
    return grade, False


def _side_grade(holistic: dict, side: str, centering_grade):
    """Per-side grade via WEAKEST-LINK of its 4 subgrades (PSA/BGS style, not an average).
    Centering uses the geometry measurement when available, else the grader's centering.
    Returns (side_grade, centering_used) or (None, None) if the side is absent."""
    s = holistic.get(side)
    if not s:
        return None, None
    cent = centering_grade if centering_grade is not None else s.get("centering")
    side_grade = pd.weakest_link([cent, s.get("corners"), s.get("edges"), s.get("surface")])
    return side_grade, cent


def _side_block(holistic: dict, side: str, grade, centering, worn_zones: list[str]) -> dict | None:
    s = holistic.get(side)
    if not s:
        return None
    return {
        "grade": grade,                      # weakest-link of the 4 subgrades (+ one-way safety floor)
        "centering": centering,              # from geometry measurement (authoritative), not the grader
        "corners": s.get("corners"),
        "edges": s.get("edges"),
        "surface": s.get("surface"),
        "worn_zones": worn_zones,            # detector evidence (MODERATE+), not the model's self-report
    }


def assemble(holistic: dict, detections: dict, warnings: list[str],
             front_centering_off=None, back_centering_off=None) -> dict:
    """Build the Decision-Card response contract from grader + detector outputs.

    Grade aggregation = WEAKEST-LINK (PSA/BGS), not a weighted average: each side's grade is
    its lowest subgrade (with a small bump if the rest are much higher), and the overall is the
    weakest side — so one bad attribute caps the card. Centering subgrades come from the
    geometry measurement (worst-axis offset) when provided by the centering step.
    """
    back = holistic.get("back")
    front_cent_g = pd.centering_grade_from_offset(front_centering_off)
    back_cent_g = pd.centering_grade_from_offset(back_centering_off) if back else None

    front_grade, front_cent = _side_grade(holistic, "front", front_cent_g)
    back_grade, back_cent = _side_grade(holistic, "back", back_cent_g)

    front_worn = _evidence(detections, "front")
    back_worn = _evidence(detections, "back") if back else []
    front_grade, front_floored = _safety_floor(front_grade, len(front_worn))
    back_grade, back_floored = (_safety_floor(back_grade, len(back_worn))
                                if back else (None, False))

    if back and back_grade is not None:
        # front-primary: the back gets ~1 grade of leniency so a slightly-worse back doesn't
        # cap a strong front to a tie (PSA/BGS weight the front more). A bad back still drags.
        back_lenient = min(back_grade + BACK_LENIENCY, 10.0)
        overall_raw = pd.weakest_link([front_grade, back_lenient])   # weakest side caps (not weighted avg)
    else:
        overall_raw = front_grade if front_grade is not None else holistic.get("overall_grade")
    overall = pd.build_overall(raw_overall=overall_raw)

    grade_it = overall["bucket"] in ("GEM", "MINT", "NM")   # confident action; card-value gate TODO
    return {
        "is_estimate": True,
        "footer": "Estimated condition from your photos — not an official PSA/BGS/CGC grade.",
        "overall": overall,
        "front": _side_block(holistic, "front", front_grade, front_cent, front_worn),
        "back": _side_block(holistic, "back", back_grade, back_cent, back_worn),
        "evidence": {"front": (detections or {}).get("front") or {},
                     "back": (detections or {}).get("back") or {}},
        "explanation": holistic.get("explanation", ""),
        "decision": "grade_it" if grade_it else "sell_raw",
        "safety_floor": {"front": front_floored, "back": back_floored},
        "quality_warnings": warnings,
        "_timing_ms": {"holistic": holistic.get("_ms"), "detect": detections.get("_ms")},
    }


# Report crops = the 8 analyzed regions per side (4 corners + 4 edges). Surface is NOT a crop
# zone (graded holistically). Across front+back the user sees 8 corners + 8 edges.
STATIC_CROPS_DIR = "static/pregrade_crops"
CROP_ZONES = ["TL", "TR", "BL", "BR", "TOP", "BOTTOM", "LEFT", "RIGHT"]
ZONE_LABELS = {"TL": "Top-left corner", "TR": "Top-right corner", "BL": "Bottom-left corner",
               "BR": "Bottom-right corner", "TOP": "Top edge", "BOTTOM": "Bottom edge",
               "LEFT": "Left edge", "RIGHT": "Right edge"}
ZONE_KIND = {z: ("corner" if z in ("TL", "TR", "BL", "BR") else "edge") for z in CROP_ZONES}


def _build_crops(front_img, back_img, detections, front_bytes, back_bytes) -> dict:
    """Save the per-zone crops (4 corners + 4 edges per side) and return their URLs + severity,
    so the report SHOWS the actual corner/edge close-ups the grader analyzed (decide-with-data).
    Crops are content-hashed (re-grading the same card reuses files)."""
    os.makedirs(STATIC_CROPS_DIR, exist_ok=True)
    out = {}
    for side, img, sbytes in (("front", front_img, front_bytes), ("back", back_img, back_bytes)):
        if img is None:
            out[side] = []
            continue
        h = hashlib.sha256(sbytes).hexdigest()[:16]
        crops = zone_crops(img)
        sev = (detections or {}).get(side) or {}
        items = []
        for z in CROP_ZONES:
            arr = crops.get(z)
            if arr is None:
                continue
            fname = f"{h}_{side}_{z}.png"
            path = os.path.join(STATIC_CROPS_DIR, fname)
            if not os.path.exists(path):
                try:
                    Image.fromarray(arr).save(path)
                except Exception as e:
                    print(f"[crops] save failed {fname}: {type(e).__name__}: {e}")
                    continue
            items.append({"zone": z, "label": ZONE_LABELS[z], "kind": ZONE_KIND[z],
                          "severity": sev.get(z, "CLEAN"), "url": f"/{path.replace(os.sep, '/')}"})
        out[side] = items
    return out


def grade_card(grader, front_bytes: bytes, back_bytes: bytes, card_id: str = "card",
               front_centering_off=None, back_centering_off=None) -> dict:
    """Full pipeline. `grader` is a ready ClaudeGrader. Runs the holistic grade and the
    evidence detector CONCURRENTLY (2 sync API calls). The centering offsets (worst-axis %
    from the interactive centering step) drive the centering subgrade. Returns the contract."""
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
        result = assemble(holistic, detections, warnings,
                          front_centering_off=front_centering_off,
                          back_centering_off=back_centering_off)
        # the 8 corner + 8 edge close-ups (4 corners + 4 edges per side) for the report
        result["crops"] = _build_crops(assets["front_img"], assets["back_img"],
                                       detections, front_bytes, back_bytes)
        return result
