"""Claude-based card condition grader (Anthropic SDK).

Grades a card from the TWO per-side ZONE MONTAGES we build during centering
(8 zoomed zones/side: 4 corners + 4 edges). Front and back graded SEPARATELY
across the 4 PSA pillars, then overall = front*0.65 + back*0.35.

Calibration baked into the prompt (learned from the blind 20-card test):
  1. Holo/foil/reverse-holo TEXTURE is DESIGN, not a defect. A clean holo card
     with sharp corners + clean edges is a 9.5-10, same as non-holo.
  2. INTERNAL CONSISTENCY: a side's grade must follow from detected defects.
     No detected wear -> side is 9.5/10 (do NOT sandbag to 8.5 "just in case").
     If a side grades <9 you MUST name the specific zone(s) causing it.

Needs ANTHROPIC_API_KEY in the environment.

Usage:
    g = ClaudeGrader()
    r = g.grade_montages("runs/grade_test/montage/X_front.png",
                         "runs/grade_test/montage/X_back.png")
    print(r["overall_grade"], r["front"], r["back"])
"""
from __future__ import annotations
import base64, json, os, time
from pathlib import Path
from typing import Optional
import numpy as np, cv2
from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
import anthropic

MODEL = "claude-opus-4-8"


def _card_box(img: "Image.Image"):
    """Robust card box via orange-background segmentation (TAG scans)."""
    rgb = np.asarray(img).astype(np.float32); H, W = rgb.shape[:2]; s = max(20, int(0.04 * min(W, H)))
    cor = np.concatenate([rgb[:s, :s].reshape(-1, 3), rgb[:s, -s:].reshape(-1, 3),
                          rgb[-s:, :s].reshape(-1, 3), rgb[-s:, -s:].reshape(-1, 3)])
    bg = np.median(cor, axis=0); dist = np.linalg.norm(rgb - bg, axis=2)
    m = (dist > 60).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        return 0, 0, W, H
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    return int(st[i, 0]), int(st[i, 1]), int(st[i, 0] + st[i, 2]), int(st[i, 1] + st[i, 3])


def prep_full_card(main_path: str, out_path: str, max_h: int = 900) -> Optional[str]:
    """Crop a *_MAIN.jpg to the card and downscale — the whole-card gestalt view."""
    if not os.path.exists(main_path):
        return None
    img = Image.open(main_path).convert("RGB")
    bx0, by0, bx1, by1 = _card_box(img); mg = int(0.02 * (bx1 - bx0))
    rgb = np.asarray(img)[max(0, by0 - mg):by1 + mg, max(0, bx0 - mg):bx1 + mg]
    h = min(max_h, rgb.shape[0]); w = int(rgb.shape[1] * h / rgb.shape[0])
    Image.fromarray(cv2.resize(rgb, (w, h), interpolation=cv2.INTER_AREA)).save(out_path)
    return out_path

SYSTEM_PROMPT = r"""You are a professional Pokemon card grader following PSA/BGS/CGC-style standards.
For each side you are shown TWO images: (1) the WHOLE CARD — use it to judge OVERALL condition and
centering (a card that looks beat-up overall is NOT a 9, even if a single zoom looks okay), and
(2) ZOOMED CROPS of the 8 wear zones (4 CORNERS TL/TR/BL/BR + 4 EDGES TOP/BOTTOM/LEFT/RIGHT, labeled)
— use them to confirm and locate fine whitening/wear. Reconcile both: the whole card sets the ballpark,
the zooms locate the defects.

Grade front and back SEPARATELY. Each side: 4 pillar scores (centering, corners, edges, surface)
on a 1-10 scale (half steps allowed) and a side grade. Then overall = front*0.65 + back*0.35.

## CRITICAL CALIBRATION (follow exactly)
0. USE THE FULL 1-10 SCALE AND COMMIT. Clustering every card around 8-8.5 is a FAILURE. A pristine
   card is 9.5-10 (not 8.5). A clearly worn card is 3-6 (not 8). Decide what you SEE and grade it
   decisively — do not hedge toward the middle, in either direction.
1. HOLO / FOIL / REVERSE-HOLO TEXTURE, rainbow shimmer, glitter, and scan-lighting gradients are the
   card's DESIGN / capture artifacts, NOT damage. NEVER lower a grade for them. A holo card with sharp
   corners and clean edges is 9.5-10, identical to a non-holo card.
2. GEM side -> grade it 10, not 8.5. If a side's corners look sharp and edges clean, with only factory
   texture / holo / lighting, that side is 9.5-10 and worn_zones is EMPTY. Do NOT flag a zone for
   "slight softening" or anything ambiguous — flag ONLY clear WHITENING (visible white cardstock at a
   worn edge/corner) or obvious ROUNDING/chipping you are confident about. When unsure, it is CLEAN.
3. WORN side -> grade it decisively low. If you see clear whitening on multiple edges/corners, or
   rounded/chipped corners, the side is 4-6 (heavy = 2-3). Do NOT round worn cards up to 8. List every
   worn zone in worn_zones.
4. A side's grade MUST follow from worn_zones: empty -> 9.5-10; 1-2 minor -> 8-9; several/heavy -> <=6.
   No unexplained downgrades and no unexplained leniency.
5. A visible crease or hard dent caps the whole card at 6.

## Whitening reference
Whitening shows as WHITE/light specks or a worn lighter rim where the colored border has rubbed off.
Most common on EDGES and CORNERS. On a dark border it shows as light specks; on a light/holo border
it is hard to see (be conservative there — don't over-call).

## Grade scale (1-10)
10 Gem Mint: flawless, sharp corners, clean edges. 9 Mint: one micro touch. 8 NM-Mint: a couple of
small visible flaws. 7 NM: multiple small flaws. 6 EX-Mint: clear edge wear / soft corners.
5 EX: heavier play, rounding + whitening. 3-4 VG: heavy whitening / creases. 1-2 Poor: severe damage.

## Per-side combine
The lowest pillar heavily constrains the side grade (NOT a plain average). worn_zones lists the
zone codes with detected wear; for each, set zone_notes describing the defect.

## Uncertainty (grade_distribution)
Grading from photos is uncertain. In grade_distribution give 2-4 plausible OVERALL grades with
probabilities that sum to 1.0, centered on overall_grade and reflecting honest uncertainty
(e.g. a clear gem -> [{10:0.6},{9.5:0.4}]; an ambiguous played card -> [{6:0.5},{5.5:0.3},{6.5:0.2}]).
Wider spread = less sure. overall_grade should equal your single most likely grade.

You MUST return ONLY the structured JSON object requested."""

COUNT_FIRST_PROMPT = r"""You are a professional Pokemon card grader (PSA/BGS/CGC style). For each side you
get the WHOLE CARD + zoomed crops of 8 wear zones (4 corners TL/TR/BL/BR + 4 edges TOP/BOTTOM/LEFT/RIGHT).

MANDATORY PROCEDURE — do this BEFORE giving any grade:
STEP 1: For EACH of the 8 zones classify wear severity as CLEAN / MINOR / MODERATE / HEAVY.
  CLEAN = sharp, no whitening, only factory texture/holo/lighting.
  MINOR = a tiny white speck or faint softening.
  MODERATE = clear whitening or visible rounding.
  HEAVY = heavy whitening / white cardstock exposed / rounded-chipped corner / fraying.
  Write every zone's verdict in zone_notes, e.g. "TL:HEAVY TR:MODERATE BL:CLEAN ... RIGHT:MODERATE".
STEP 2: count zones at MODERATE-or-worse (n_mod) and at HEAVY (n_heavy).
STEP 3: map to the side grade by this HARD rubric (no hedging toward the middle):
  n_mod 0           -> 9.5-10
  n_mod 1-2, n_heavy 0 -> 7.5-8.5
  n_mod 3-5, n_heavy<=1 -> 5.5-7
  n_mod 6-8 OR n_heavy>=3 -> 3-4.5
  n_heavy>=6 OR a visible crease/dent -> 1-2
HARD RULE: if you see clear whitening on 3+ zones spanning BOTH corners AND edges, the side is <=5,
NEVER 7+. Heavily-played cards land 2-5, not 6-8.

CALIBRATION: holo/foil texture, rainbow shimmer, scan-lighting gradients are DESIGN not damage -> CLEAN.
Use the FULL 1-10 scale; do NOT cluster grades at 8. The whole-card image sets overall condition; the
zooms locate/confirm the wear.

overall = front*0.65 + back*0.35. worn_zones = zones at MODERATE-or-worse. Fill grade_distribution with
2-4 plausible grades summing to 1.0. Return ONLY the structured JSON."""

_SIDE = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "grade": {"type": "number"},
        "centering": {"type": "number"},
        "corners": {"type": "number"},
        "edges": {"type": "number"},
        "surface": {"type": "number"},
        "worn_zones": {"type": "array", "items": {"type": "string",
            "enum": ["TL", "TR", "BL", "BR", "TOP", "BOTTOM", "LEFT", "RIGHT"]}},
        "zone_notes": {"type": "string"},
    },
    "required": ["grade", "centering", "corners", "edges", "surface", "worn_zones", "zone_notes"],
}
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "front": _SIDE,
        "back": {"anyOf": [_SIDE, {"type": "null"}]},
        "overall_grade": {"type": "number"},
        "grade_distribution": {
            "type": "array",
            "description": "2-4 plausible overall grades with probabilities that SUM TO 1.0, "
                           "reflecting your honest uncertainty. Most confident grade gets the highest prob.",
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {"grade": {"type": "number"}, "prob": {"type": "number"}},
                "required": ["grade", "prob"],
            },
        },
        "grade_label": {"type": "string"},
        "explanation": {"type": "string"},
    },
    "required": ["front", "back", "overall_grade", "grade_distribution", "grade_label", "explanation"],
}


REGRADE_PROMPT = r"""You are a Pokemon-card grader. An expert INSPECTOR has ALREADY classified the wear
severity of every border zone, and you are given those findings explicitly. TRUST the inspector — do NOT
re-interpret clear wear as 'minor' or dismiss it as factory texture (the inspector already excluded
holo/foil/lighting). Your job is ONLY to map the findings to a grade, using the images to judge how bad
each flagged zone is.

Per side, count zones MODERATE-or-worse (n_mod) and HEAVY (n_heavy), then:
  n_mod 0              -> 9.5-10
  n_mod 1-2, n_heavy 0 -> 8-9
  n_mod 3-5, n_heavy<=1 -> 5.5-7
  n_mod 6-8 OR n_heavy>=3 -> 3-4.5
  n_heavy>=6 OR visible crease/dent -> 1-2
overall = front*0.65 + back*0.35. Put the flagged zones in worn_zones and fill grade_distribution
(2-4 grades summing to 1.0). Use the FULL scale; a card the inspector found heavily worn must NOT be 7+.
Return ONLY the structured JSON."""

DETECT_PROMPT = r"""You are a meticulous Pokemon-card condition INSPECTOR. For each side you get the WHOLE
CARD + a montage of 8 labeled border zones (4 corners TL/TR/BL/BR, 4 edges TOP/BOTTOM/LEFT/RIGHT).
Your ONLY job: classify the WEAR SEVERITY of EACH of the 8 zones. Do NOT output a grade.

Severity scale:
  CLEAN    = sharp, solid border, no whitening/marks. Holo shimmer, foil sparkle, factory print texture,
             and studio-lighting gradients are NOT wear -> CLEAN.
  MINOR    = a few small white specks, or faint softening/rounding.
  MODERATE = clear WHITENING (a lighter worn rim where the colored border rubbed off to white cardstock),
             visible rounding, or a distinct dark dirt/scuff mark.
  HEAVY    = heavy whitening / white cardstock exposed / frayed fibers / chipped or badly rounded corner /
             heavy black scuffing.

Be EXHAUSTIVE and LITERAL — report real whitening/dirt even when subtle, especially on DARK borders where
it shows as lighter fraying/streaks. But a pristine card MUST come back all CLEAN. Output a severity for
all 8 zones of each side."""

_SEV = {"type": "string", "enum": ["CLEAN", "MINOR", "MODERATE", "HEAVY"]}
_ZONES8 = {
    "type": "object", "additionalProperties": False,
    "properties": {z: _SEV for z in ("TL", "TR", "BL", "BR", "TOP", "BOTTOM", "LEFT", "RIGHT")},
    "required": ["TL", "TR", "BL", "BR", "TOP", "BOTTOM", "LEFT", "RIGHT"],
}
DETECT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"front": _ZONES8, "back": {"anyOf": [_ZONES8, {"type": "null"}]}},
    "required": ["front", "back"],
}


def _img_block(path: str) -> dict:
    data = base64.standard_b64encode(Path(path).read_bytes()).decode("utf-8")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}


class ClaudeGrader:
    def __init__(self, api_key: Optional[str] = None, model: str = MODEL, thinking: bool = True,
                 variant: str = "base"):
        self.client = anthropic.Anthropic(api_key=api_key)  # reads ANTHROPIC_API_KEY if None
        self.model = model
        self.thinking = thinking
        self.system = COUNT_FIRST_PROMPT if variant == "count_first" else SYSTEM_PROMPT

    def grade_montages(self, front_montage: str, back_montage: Optional[str] = None,
                       front_full: Optional[str] = None, back_full: Optional[str] = None) -> dict:
        t0 = time.time()
        content: list = []
        content.append({"type": "text", "text": "=== FRONT side ==="})
        if front_full and os.path.exists(front_full):
            content += [{"type": "text", "text": "Whole FRONT card (overall condition + centering):"}, _img_block(front_full)]
        content += [{"type": "text", "text": "Zoomed FRONT wear zones (4 corners + 4 edges, labeled):"}, _img_block(front_montage)]
        if back_montage and os.path.exists(back_montage):
            content.append({"type": "text", "text": "=== BACK side ==="})
            if back_full and os.path.exists(back_full):
                content += [{"type": "text", "text": "Whole BACK card:"}, _img_block(back_full)]
            content += [{"type": "text", "text": "Zoomed BACK wear zones:"}, _img_block(back_montage)]
        else:
            content += [{"type": "text", "text": "No BACK image provided. Set back=null and overall=front grade."}]
        content.append({"type": "text", "text": "Grade this card. Return the structured JSON only."})

        kwargs = dict(
            model=self.model, max_tokens=4096, system=self.system,
            messages=[{"role": "user", "content": content}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        )
        if self.thinking:
            kwargs["thinking"] = {"type": "adaptive"}
            kwargs["output_config"]["effort"] = "medium"
        resp = self.client.messages.create(**kwargs)

        text = next((b.text for b in resp.content if b.type == "text"), "")
        data = json.loads(text)
        data["_usage"] = {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}
        data["_ms"] = round((time.time() - t0) * 1000)
        data["_model"] = resp.model
        return data

    def regrade_with_evidence(self, detections: dict, front_montage: str, back_montage: Optional[str] = None,
                              front_full: Optional[str] = None, back_full: Optional[str] = None) -> dict:
        """STAGE 3 (user's flow): re-grade a card while EXPLICITLY GIVEN the inspector's per-zone wear
        findings, so the grader can't conservatively ignore them. Map severity -> grade by the rubric."""
        t0 = time.time()
        def fmt(side):
            z = detections.get(side) or {}
            worn = {k: v for k, v in z.items() if v in ("MODERATE", "HEAVY")}  # drop noisy MINOR
            return ", ".join(f"{k}:{v}" for k, v in worn.items()) or "no moderate/heavy wear"
        ev = f"INSPECTOR FINDINGS (trust these — do not downgrade them):\n  FRONT: {fmt('front')}\n  BACK: {fmt('back')}"
        content: list = [{"type": "text", "text": ev}, {"type": "text", "text": "=== FRONT ==="}]
        if front_full and os.path.exists(front_full):
            content += [{"type": "text", "text": "Whole FRONT card:"}, _img_block(front_full)]
        content += [{"type": "text", "text": "FRONT zones:"}, _img_block(front_montage)]
        if back_montage and os.path.exists(back_montage):
            content.append({"type": "text", "text": "=== BACK ==="})
            if back_full and os.path.exists(back_full):
                content += [{"type": "text", "text": "Whole BACK card:"}, _img_block(back_full)]
            content += [{"type": "text", "text": "BACK zones:"}, _img_block(back_montage)]
        content.append({"type": "text", "text": "Assign the final grade per the rubric. Return JSON only."})
        kwargs = dict(model=self.model, max_tokens=4096, system=REGRADE_PROMPT,
                      messages=[{"role": "user", "content": content}],
                      output_config={"format": {"type": "json_schema", "schema": SCHEMA}})
        if self.thinking:
            kwargs["thinking"] = {"type": "adaptive"}; kwargs["output_config"]["effort"] = "medium"
        resp = self.client.messages.create(**kwargs)
        data = json.loads(next((b.text for b in resp.content if b.type == "text"), ""))
        data["_usage"] = {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}
        data["_ms"] = round((time.time() - t0) * 1000)
        return data

    def detect_zones(self, front_montage: str, back_montage: Optional[str] = None,
                     front_full: Optional[str] = None, back_full: Optional[str] = None) -> dict:
        """STAGE A: per-zone wear severity (CLEAN/MINOR/MODERATE/HEAVY). High-recall, precision-guarded.
        Separate from grading so the 'don't over-call' grade calibration can't suppress detection."""
        t0 = time.time()
        content: list = [{"type": "text", "text": "=== FRONT side ==="}]
        if front_full and os.path.exists(front_full):
            content += [{"type": "text", "text": "Whole FRONT card:"}, _img_block(front_full)]
        content += [{"type": "text", "text": "FRONT 8 zones:"}, _img_block(front_montage)]
        if back_montage and os.path.exists(back_montage):
            content.append({"type": "text", "text": "=== BACK side ==="})
            if back_full and os.path.exists(back_full):
                content += [{"type": "text", "text": "Whole BACK card:"}, _img_block(back_full)]
            content += [{"type": "text", "text": "BACK 8 zones:"}, _img_block(back_montage)]
        else:
            content += [{"type": "text", "text": "No BACK image. Set back=null."}]
        content.append({"type": "text", "text": "Classify wear severity of every zone. Return JSON only."})
        kwargs = dict(model=self.model, max_tokens=2048, system=DETECT_PROMPT,
                      messages=[{"role": "user", "content": content}],
                      output_config={"format": {"type": "json_schema", "schema": DETECT_SCHEMA}})
        if self.thinking:
            kwargs["thinking"] = {"type": "adaptive"}; kwargs["output_config"]["effort"] = "low"
        resp = self.client.messages.create(**kwargs)
        data = json.loads(next((b.text for b in resp.content if b.type == "text"), ""))
        data["_usage"] = {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}
        data["_ms"] = round((time.time() - t0) * 1000)
        return data
