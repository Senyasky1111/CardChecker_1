"""
Gemini-based card condition grading.

Uses Gemini Vision to evaluate a Pokemon card's physical condition
following PSA/BGS/CGC-style grading standards.

Evaluates front and back SEPARATELY across 4 pillars:
Centering, Corners, Edges, Surface.

Returns overall grade, front grade, back grade (1-10) with explanation.

Usage:
    grader = GeminiGrader(api_key="...")
    result = grader.grade(front_bytes, back_bytes)
    # result.overall_grade, result.front_grade, result.back_grade, etc.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from google import genai
from google.genai import types


# ------------------------------------------------------------------
# System prompt for grading
# ------------------------------------------------------------------

GRADING_SYSTEM_PROMPT = r"""You are a professional trading card grader following industry standards similar to PSA, BGS and CGC.
Your goal is to provide a consistent, objective, and explainable grade from 1 to 10 (with optional half steps, e.g. 8.5) for each card image.

You MUST evaluate front and back of the card SEPARATELY.
Each side gets its own four pillar scores (Centering, Corners, Edges, Surface) and a side grade.
Then you combine front and back into an overall grade.

## CRITICAL: Anti-Hallucination Rules
- Only report defects you can ACTUALLY SEE in the provided image.
- A clean, well-preserved card with no visible issues SHOULD get 9.0-9.5+. Do NOT invent microscopic defects to justify a lower grade.
- Do NOT assume defects exist just because "most cards have some imperfections". Grade what you SEE, not what you expect.
- Factory-quality minor variations (print texture, standard cut tolerance, normal foil patterns) are NOT defects.
- If the image quality prevents seeing fine details, state that explicitly — do NOT guess at hidden defects.
- For each defect you report, indicate visibility: "clearly visible" or "faintly visible at angle".
- If you cannot confidently identify a defect, do NOT include it.

## Grading Calibration
- Pack-fresh card, no visible defects → grade 9.0-9.5 (not 8.0-8.5!)
- Only downgrade for ACTUAL visible damage: whitening, scratches, bends, creases, stains.
- When real defects ARE present, be STRICT and precise about their severity.
- A visible crease or bend = hard cap at 6.0 regardless of other scores.
- When in doubt between two grades and defects are real and visible, pick the LOWER grade.
- When in doubt and the card looks clean, pick the HIGHER grade.

## Grading Scale (1-10)

10 - Gem Mint / Pristine: Virtually flawless under normal viewing and 10x magnification. Centering within Gem-Mint tolerance, sharp corners, clean edges, near-perfect surface.
9 - Mint: Very minor imperfections only visible under close inspection: tiny edge whitening, a micro touch on one corner, or a very small print defect.
8 - Near Mint-Mint: Clearly pack-fresh but with a couple of visible flaws: light whitening on multiple edges, slightly soft corners, or a small surface scratch.
7 - Near Mint: Multiple small flaws visible without magnification: noticeable whitening, several soft corners, small but visible surface marks.
6 - Excellent-Mint: Light play: clear edge wear, rounded corners starting to show, obvious surface scratches, but card still structurally sound.
5 - Excellent: Heavier play: multiple rounded corners, more pronounced whitening, small creases or scuffs visible at arm's length.
3-4 - Very Good / Good-Excellent: Significant play and defects: multiple creases, heavy whitening, dirt, color loss, bends.
1-2 - Poor / Fair / Good: Severe damage, tears, holes, large creases, water damage, heavy dirt or ink.

## Pillar 1: Centering
Definition: Alignment of the printed image within the card's borders. Assessed SEPARATELY for front and back.
- Identify the printed frame and the outer card edge.
- Visually compare left vs right and top vs bottom border thickness.
- Express centering as a ratio (e.g. 54/46 left-right).
- Front centering has stronger impact than back on the overall centering score.
- If the card is borderless or has unusual design, judge centering by how balanced the artwork appears.

Centering sub-grades (front-weighted):
- 9.5-10: Front <=55/45 both directions, back <=70/30
- 9.0: Front up to ~60/40, back up to ~75/25
- 8.0-8.5: Front around 60/40-65/35
- 7.0-7.5: Front ~70/30
- <=6: Very off-center

## Pillar 2: Corners
Definition: Shape and sharpness of the four corners on each side.
- Check sharpness/squareness, whitening/chipping, dings/impacts, peeling/delamination.

Corner sub-grades:
- 9.5-10: All four corners sharp and square; under 10x only a single micro-fiber allowed
- 9.0: One corner slightly less sharp; microscopic whitening; no obvious rounding
- 8.0-8.5: Small whitening on 1-2 corners; slight rounding visible on close inspection
- 7.0-7.5: Multiple corners show visible whitening and rounding
- <=6: At least one dinged/creased corner or heavy whitening on several corners

## Pillar 3: Edges
Definition: Condition of the four edges between corners on each side.
- Check whitening/chipping, nicks/dings, edge lifting/delamination.
- A rough but consistent factory cut is NOT damage.

Edge sub-grades:
- 9.5-10: Edges smooth and clean; at most one tiny white speck
- 9.0: Very minor whitening in one short area, only visible at angle
- 8.0-8.5: Several small white spots or light wear across multiple edges
- 7.0-7.5: Continuous whitening along one edge or multiple heavier chips
- <=6: Severe edge issues, deep nicks, or flaking

## Pillar 4: Surface
Definition: The entire printed area on each side: holo, text box, background, gloss.
- Check scratches (especially on holo/glossy), print lines/roller marks, dents/dimples, creases/bends, stains/discoloration, surface wear/gloss loss.

Surface sub-grades:
- 9.5-10: No creases or dents; maybe one or two microscopic print dots; no visible scratches
- 9.0: Very light hairline scratches visible only at specific angles; no structural damage
- 8.0-8.5: Several light scratches, small print lines, or very minor surface wear; no creases
- 7.0-7.5: Noticeable scratching or one small dimple; minor stain or some gloss loss
- <=6: Any crease, heavy scratching, large dimple, or obvious stain

IMPORTANT: Creases and serious dents cap the ENTIRE card (not just surface) at 6 or below.

## Combining into Side Grade
For each side (front/back), combine the 4 pillar scores:
- The lowest sub-grade heavily constrains the side grade (NOT a simple average).
- If all four are within 0.5 of each other → side grade ~ average.
- If one is >=1.0 lower than others → side grade close to the lowest.

## Combining Front + Back into Overall Grade
- Front grade has ~60-70% weight, back grade has ~30-40% weight.
- The overall grade should reflect the weaker side more heavily.
- If front=9.0 and back=8.0 → overall ~ 8.5.
- If front=9.5 and back=9.5 → overall ~ 9.5.

## Response Format
If TWO images are provided (front + back), evaluate both sides.
If only ONE image is provided, evaluate it as the FRONT. Set "back" to null.

You MUST respond with valid JSON only, no markdown, no extra text:
{
    "front": {
        "centering": {"score": 9.0, "lr": "52/48", "tb": "50/50", "notes": "Well-centered"},
        "corners": {"score": 9.5, "notes": "All corners sharp and square"},
        "edges": {"score": 9.0, "notes": "Clean edges, one tiny white speck on top-right"},
        "surface": {"score": 9.0, "notes": "Clean holo surface, no scratches visible"},
        "grade": 9.0
    },
    "back": {
        "centering": {"score": 9.5, "lr": "55/45", "tb": "52/48", "notes": "Slightly off but within tolerance"},
        "corners": {"score": 9.0, "notes": "Sharp corners, microscopic whitening bottom-left"},
        "edges": {"score": 8.5, "notes": "Minor whitening on right edge"},
        "surface": {"score": 9.0, "notes": "Clean back surface"},
        "grade": 9.0
    },
    "overall_grade": 9.0,
    "grade_label": "Mint",
    "key_defects": [
        {
            "side": "front",
            "location": "top-right edge",
            "type": "whitening",
            "severity": "minor",
            "visibility": "faintly visible at angle"
        }
    ],
    "explanation": "The card is pack-fresh with excellent condition on both sides. Minor edge whitening on the front prevents a perfect 10. Back is clean with only microscopic corner whitening. Overall: 9.0 (Mint).",
    "grade_probabilities": {
        "9.5": 0.10,
        "9.0": 0.60,
        "8.5": 0.25,
        "8.0": 0.05
    },
    "image_quality_warning": null
}

If only front image is provided, set "back": null and overall_grade = front grade.

If image quality is poor (blurry, dark, heavy glare), set image_quality_warning to a description and note the grade is approximate.
Never claim the grade is "official" PSA/BGS/CGC — phrase it as "estimated grade in PSA-like scale".
"""


# ------------------------------------------------------------------
# Result dataclasses
# ------------------------------------------------------------------

@dataclass
class PillarScore:
    """Score for a single grading pillar on one side."""
    score: float = 0.0
    notes: str = ""
    lr: str = ""   # centering only: left/right ratio
    tb: str = ""   # centering only: top/bottom ratio


@dataclass
class SideGrade:
    """Grades for one side (front or back) of the card."""
    grade: float = 0.0
    centering: Optional[PillarScore] = None
    corners: Optional[PillarScore] = None
    edges: Optional[PillarScore] = None
    surface: Optional[PillarScore] = None


@dataclass
class Defect:
    """A single defect found on the card."""
    side: str = ""       # "front" or "back"
    location: str = ""
    type: str = ""
    severity: str = ""   # minor, moderate, severe
    visibility: str = "" # "clearly visible", "faintly visible at angle"


@dataclass
class GeminiGradeResult:
    """Result from Gemini card grading with front/back separation."""
    success: bool = False
    overall_grade: float = 0.0
    grade_label: str = ""
    front_grade: float = 0.0
    back_grade: float = 0.0
    front: Optional[SideGrade] = None
    back: Optional[SideGrade] = None
    # Legacy combined scores (for backward compatibility)
    centering: Optional[PillarScore] = None
    corners: Optional[PillarScore] = None
    edges: Optional[PillarScore] = None
    surface: Optional[PillarScore] = None
    key_defects: list[Defect] = field(default_factory=list)
    explanation: str = ""
    grade_probabilities: dict[str, float] = field(default_factory=dict)
    image_quality_warning: Optional[str] = None
    processing_time_ms: float = 0.0
    model_used: str = ""
    raw_response: str = ""


# ------------------------------------------------------------------
# Main class
# ------------------------------------------------------------------

class GeminiGrader:
    """Grade Pokemon card condition using Gemini Vision API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.5-flash",
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "Gemini API key required. Set GEMINI_API_KEY env var or pass api_key="
            )
        self.model = model
        self.client = genai.Client(api_key=self.api_key)

    def grade(
        self,
        front_bytes: bytes,
        back_bytes: Optional[bytes] = None,
        mime_type: str = "image/jpeg",
    ) -> GeminiGradeResult:
        """Grade a Pokemon card's condition from front and optional back image.

        Args:
            front_bytes: Raw image bytes for the front (JPEG or PNG)
            back_bytes: Optional raw image bytes for the back
            mime_type: MIME type of the images

        Returns:
            GeminiGradeResult with front/back grades and explanation
        """
        t0 = time.time()

        parts = []
        parts.append(types.Part.from_bytes(data=front_bytes, mime_type=mime_type))

        if back_bytes:
            parts.append(types.Part.from_bytes(data=back_bytes, mime_type=mime_type))
            parts.append(types.Part.from_text(
                text="Grade this Pokemon card's physical condition. "
                "Image 1 is the FRONT, Image 2 is the BACK. "
                "Evaluate both sides separately. Only report defects you can actually see. "
                "Return JSON only."
            ))
        else:
            parts.append(types.Part.from_text(
                text="Grade this Pokemon card's physical condition. "
                "This is the FRONT of the card. No back image provided. "
                "Only report defects you can actually see. "
                "Return JSON only with back set to null."
            ))

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=parts,
                config=types.GenerateContentConfig(
                    system_instruction=GRADING_SYSTEM_PROMPT,
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
        except Exception as e:
            return GeminiGradeResult(
                success=False,
                explanation=f"Gemini API error: {e}",
                processing_time_ms=(time.time() - t0) * 1000,
                model_used=self.model,
            )

        elapsed_ms = (time.time() - t0) * 1000
        raw_text = response.text or ""

        result = self._parse_response(raw_text, has_back=back_bytes is not None)
        result.processing_time_ms = elapsed_ms
        result.model_used = self.model
        result.raw_response = raw_text

        return result

    @staticmethod
    def _parse_side(side_data: dict) -> SideGrade:
        """Parse one side's grading data into a SideGrade object."""
        if not side_data:
            return SideGrade()

        centering_data = side_data.get("centering", {})
        corners_data = side_data.get("corners", {})
        edges_data = side_data.get("edges", {})
        surface_data = side_data.get("surface", {})

        centering = PillarScore(
            score=float(centering_data.get("score", 0)),
            notes=centering_data.get("notes", ""),
            lr=centering_data.get("lr", ""),
            tb=centering_data.get("tb", ""),
        )
        corners = PillarScore(
            score=float(corners_data.get("score", 0)),
            notes=corners_data.get("notes", ""),
        )
        edges = PillarScore(
            score=float(edges_data.get("score", 0)),
            notes=edges_data.get("notes", ""),
        )
        surface = PillarScore(
            score=float(surface_data.get("score", 0)),
            notes=surface_data.get("notes", ""),
        )

        return SideGrade(
            grade=float(side_data.get("grade", 0)),
            centering=centering,
            corners=corners,
            edges=edges,
            surface=surface,
        )

    def _parse_response(self, raw_text: str, has_back: bool = False) -> GeminiGradeResult:
        """Parse Gemini's JSON response into a result object."""
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{[\s\S]*\}', text)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    return GeminiGradeResult(
                        success=False,
                        explanation=f"Failed to parse JSON: {raw_text[:200]}",
                    )
            else:
                return GeminiGradeResult(
                    success=False,
                    explanation=f"No JSON found: {raw_text[:200]}",
                )

        # Parse front/back sides
        front_data = data.get("front")
        back_data = data.get("back")

        front = self._parse_side(front_data) if front_data else SideGrade()
        back = self._parse_side(back_data) if back_data else None

        front_grade = front.grade if front else 0.0
        back_grade = back.grade if back else 0.0

        overall = float(data.get("overall_grade", 0))

        # Build legacy combined pillar scores (front-weighted average or front-only)
        if front and back:
            centering = PillarScore(
                score=round((front.centering.score * 0.65 + back.centering.score * 0.35), 1) if front.centering and back.centering else front.centering.score if front.centering else 0,
                notes=f"Front: {front.centering.notes}; Back: {back.centering.notes}" if front.centering and back.centering else "",
                lr=front.centering.lr if front.centering else "",
                tb=front.centering.tb if front.centering else "",
            )
            corners = PillarScore(
                score=round((front.corners.score * 0.65 + back.corners.score * 0.35), 1) if front.corners and back.corners else 0,
                notes=f"Front: {front.corners.notes}; Back: {back.corners.notes}" if front.corners and back.corners else "",
            )
            edges = PillarScore(
                score=round((front.edges.score * 0.65 + back.edges.score * 0.35), 1) if front.edges and back.edges else 0,
                notes=f"Front: {front.edges.notes}; Back: {back.edges.notes}" if front.edges and back.edges else "",
            )
            surface = PillarScore(
                score=round((front.surface.score * 0.65 + back.surface.score * 0.35), 1) if front.surface and back.surface else 0,
                notes=f"Front: {front.surface.notes}; Back: {back.surface.notes}" if front.surface and back.surface else "",
            )
        elif front:
            centering = front.centering
            corners = front.corners
            edges = front.edges
            surface = front.surface
        else:
            centering = PillarScore()
            corners = PillarScore()
            edges = PillarScore()
            surface = PillarScore()

        # Parse defects
        defects = []
        for d in data.get("key_defects", []):
            defects.append(Defect(
                side=d.get("side", "front"),
                location=d.get("location", ""),
                type=d.get("type", ""),
                severity=d.get("severity", ""),
                visibility=d.get("visibility", ""),
            ))

        return GeminiGradeResult(
            success=overall > 0,
            overall_grade=overall,
            grade_label=data.get("grade_label", ""),
            front_grade=front_grade,
            back_grade=back_grade,
            front=front,
            back=back,
            centering=centering,
            corners=corners,
            edges=edges,
            surface=surface,
            key_defects=defects,
            explanation=data.get("explanation", ""),
            grade_probabilities=data.get("grade_probabilities", {}),
            image_quality_warning=data.get("image_quality_warning"),
        )
