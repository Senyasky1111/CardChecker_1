"""
Gemini-based card condition grading.

Uses Gemini Vision to evaluate a Pokemon card's physical condition
following PSA/BGS/CGC-style grading standards.

Evaluates 4 pillars: Centering, Corners, Edges, Surface.
Returns overall grade (1-10) with explanation.

Usage:
    grader = GeminiGrader(api_key="...")
    result = await grader.grade(image_bytes)
    # result.overall_grade, result.centering, result.explanation, etc.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from google import genai
from google.genai import types


# ------------------------------------------------------------------
# System prompt for grading (based on user's professional prompt)
# ------------------------------------------------------------------

GRADING_SYSTEM_PROMPT = r"""You are a professional trading card grader following industry standards similar to PSA, BGS and CGC.
Your goal is to provide a consistent, objective, and explainable grade from 1 to 10 (with optional half steps, e.g. 8.5) for each card image, plus a short explanation.
You must evaluate four core condition pillars:
Centering, Corners, Edges, Surface.
You then combine these into an overall grade similar to professional grading companies.

## Grading Scale (High-Level)
Use a 1-10 scale, aligned conceptually with PSA/BGS/CGC:

10 - Gem Mint / Pristine: Virtually flawless under normal viewing and 10x magnification. Centering within Gem-Mint tolerance, sharp corners, clean edges, and near-perfect surface (only microscopic print dots allowed).
9 - Mint: Very minor imperfections only visible under close inspection: tiny edge whitening, a micro touch on one corner, or a very small print defect.
8 - Near Mint-Mint: Clearly pack-fresh but with a couple of visible flaws: light whitening on multiple edges, slightly soft corners, or a small surface scratch.
7 - Near Mint: Multiple small flaws visible without magnification: noticeable whitening, several soft corners, small but visible surface marks.
6 - Excellent-Mint: Light play: clear edge wear, rounded corners starting to show, obvious surface scratches, but card still structurally sound.
5 - Excellent: Heavier play: multiple rounded corners, more pronounced whitening, small creases or scuffs visible at arm's length.
3-4 - Very Good / Good-Excellent: Significant play and defects: multiple creases, heavy whitening, dirt, color loss, bends.
1-2 - Poor / Fair / Good: Severe damage, tears, holes, large creases, water damage, heavy dirt or ink.

When in doubt between two grades, pick the LOWER one unless defects are extremely minor.

## Pillar 1: Centering
Definition: Alignment of the printed image within the card's borders.
- Visually compare left vs right and top vs bottom border thickness.
- Express centering as a ratio (e.g. 54/46).
- Front centering has stronger impact than back.
- 9.5-10: Front <=55/45, back <=70/30
- 9.0: Front up to ~60/40, back up to ~75/25
- 8.0-8.5: Front around 60/40-65/35
- 7.0-7.5: Front ~70/30
- <=6: Very off-center

## Pillar 2: Corners
Definition: Shape and sharpness of the four corners.
- Check sharpness/squareness, whitening/chipping, dings/impacts, peeling.
- 9.5-10: All four corners sharp and square
- 9.0: One corner slightly less sharp; microscopic whitening
- 8.0-8.5: Small whitening on 1-2 corners; slight rounding
- 7.0-7.5: Multiple corners show visible whitening and rounding
- <=6: At least one dinged/creased corner or heavy whitening

## Pillar 3: Edges
Definition: Condition of the four edges between corners.
- Check whitening/chipping, nicks/dings, edge lifting.
- 9.5-10: Edges smooth and clean; at most one tiny white speck
- 9.0: Very minor whitening in one short area
- 8.0-8.5: Several small white spots or light wear across multiple edges
- 7.0-7.5: Continuous whitening along one edge or multiple heavier chips
- <=6: Severe edge issues, deep nicks, or flaking

## Pillar 4: Surface
Definition: The entire printed area on both front and back.
- Check scratches, print lines, dents/dimples, creases/bends, stains, surface wear.
- 9.5-10: No creases or dents; maybe one or two microscopic print dots
- 9.0: Very light hairline scratches visible only at specific angles
- 8.0-8.5: Several light scratches, small print lines, or very minor surface wear
- 7.0-7.5: Noticeable scratching or one small dimple; minor stain
- <=6: Any crease, heavy scratching, large dimple, or obvious stain

IMPORTANT: Creases and serious dents cap the entire card at 6 or below.

## Combining Sub-Scores
- The lowest sub-grade heavily constrains the final grade (NOT a simple average).
- If all four sub-scores are within 0.5 of each other, overall ~ average.
- If one sub-score is >=1.0 lower than others, overall should be close to the lowest.
- Major surface or corner issues hard-cap the overall grade.

## Be STRICT with defects
When in doubt, grade LOWER. If not sure, predict probability distribution for different grades.

## Response format
You MUST respond with valid JSON only, no markdown, no extra text:
{
    "overall_grade": 8.5,
    "grade_label": "Near Mint-Mint",
    "centering": {
        "score": 8.0,
        "front_lr": "56/44",
        "front_tb": "52/48",
        "notes": "Slightly right-shifted but within NM-MT tolerance"
    },
    "corners": {
        "score": 9.0,
        "notes": "All corners sharp, microscopic whitening on bottom-left"
    },
    "edges": {
        "score": 8.5,
        "notes": "Minor whitening on top-right back edge"
    },
    "surface": {
        "score": 8.5,
        "notes": "Very light surface scratch on front holo area, visible only under angled light"
    },
    "key_defects": [
        {
            "location": "top-right back edge",
            "type": "whitening",
            "severity": "minor"
        }
    ],
    "explanation": "The card presents overall as pack-fresh with excellent corners and clean surface, but centering is slightly off left-right and there is small edge whitening on the back. These minor issues prevent a true Mint 9. Overall grade: 8.5 (Near Mint-Mint).",
    "grade_probabilities": {
        "9.0": 0.15,
        "8.5": 0.55,
        "8.0": 0.25,
        "7.5": 0.05
    },
    "image_quality_warning": null
}

If image quality is poor (blurry, dark, heavy glare), set image_quality_warning to a description of the issue and note that the grade is approximate.
Never claim the grade is "official" PSA/BGS/CGC — phrase it as "estimated grade in PSA-like scale".
"""


# ------------------------------------------------------------------
# Result dataclass
# ------------------------------------------------------------------

@dataclass
class PillarScore:
    """Score for a single grading pillar."""
    score: float = 0.0
    notes: str = ""
    front_lr: str = ""  # centering only
    front_tb: str = ""  # centering only


@dataclass
class Defect:
    """A single defect found on the card."""
    location: str = ""
    type: str = ""
    severity: str = ""  # minor, moderate, severe


@dataclass
class GeminiGradeResult:
    """Result from Gemini card grading."""
    success: bool = False
    overall_grade: float = 0.0
    grade_label: str = ""
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
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> GeminiGradeResult:
        """Grade a Pokemon card's condition from image bytes.

        Args:
            image_bytes: Raw image bytes (JPEG or PNG)
            mime_type: MIME type of the image

        Returns:
            GeminiGradeResult with grades and explanation
        """
        t0 = time.time()

        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        text_part = types.Part.from_text(
            text="Grade this Pokemon card's physical condition. "
            "Be strict with defects. Return JSON only."
        )

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[image_part, text_part],
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

        result = self._parse_response(raw_text)
        result.processing_time_ms = elapsed_ms
        result.model_used = self.model
        result.raw_response = raw_text

        return result

    def _parse_response(self, raw_text: str) -> GeminiGradeResult:
        """Parse Gemini's JSON response into a result object."""
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            import re
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

        # Parse pillar scores
        centering_data = data.get("centering", {})
        corners_data = data.get("corners", {})
        edges_data = data.get("edges", {})
        surface_data = data.get("surface", {})

        centering = PillarScore(
            score=float(centering_data.get("score", 0)),
            notes=centering_data.get("notes", ""),
            front_lr=centering_data.get("front_lr", ""),
            front_tb=centering_data.get("front_tb", ""),
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

        # Parse defects
        defects = []
        for d in data.get("key_defects", []):
            defects.append(Defect(
                location=d.get("location", ""),
                type=d.get("type", ""),
                severity=d.get("severity", ""),
            ))

        overall = float(data.get("overall_grade", 0))

        return GeminiGradeResult(
            success=overall > 0,
            overall_grade=overall,
            grade_label=data.get("grade_label", ""),
            centering=centering,
            corners=corners,
            edges=edges,
            surface=surface,
            key_defects=defects,
            explanation=data.get("explanation", ""),
            grade_probabilities=data.get("grade_probabilities", {}),
            image_quality_warning=data.get("image_quality_warning"),
        )
