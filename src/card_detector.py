"""
Card detection and perspective correction for Pokemon cards.

Detects a card quadrilateral in a photo and warps it to a canonical
top-down view (600x825 px, matching the 63x88 mm card ratio).

Detection backends:
- OpenCV (CardDetector): contour + Hough line detection (fast, no model needed)
- YOLO-pose (YOLOCardDetector): neural network with corner keypoints (accurate)

Use get_detector() factory to select backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image

# Canonical output size (matches dataset images & OCR expectations)
CARD_W = 600
CARD_H = 825
CARD_ASPECT = 63 / 88  # width / height ≈ 0.716


def check_passthrough(image: Image.Image) -> "DetectionResult | None":
    """Return a passthrough result if the image is already a clean card crop.

    Checks aspect ratio (within ±5% of card ratio) and resolution (350-900px wide).
    If matched, returns a simple LANCZOS resize instead of running detection.
    """
    w, h = image.size
    if h == 0:
        return None
    aspect = w / h
    if abs(aspect - CARD_ASPECT) < 0.05 and 350 <= w <= 900:
        warped = image.resize((CARD_W, CARD_H), Image.LANCZOS)
        corners = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
        return DetectionResult(
            corners=corners,
            confidence=1.0,
            method="passthrough",
            card_found=True,
            warped=warped,
        )
    return None


@dataclass
class DetectionResult:
    """Result of card detection in an image."""
    corners: np.ndarray          # 4x2 float32, ordered TL/TR/BR/BL
    confidence: float            # 0.0–1.0
    method: str                  # "contour", "hough", "fallback", "yolo"
    card_found: bool             # True if a card-like quad was found
    warped: Optional[Image.Image] = None  # perspective-corrected card image


# ------------------------------------------------------------------
# Shared geometry helpers (used by both OpenCV and YOLO detectors)
# ------------------------------------------------------------------

def order_corners(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as: top-left, top-right, bottom-right, bottom-left."""
    pts = pts.astype(np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).flatten()

    ordered = np.zeros((4, 2), dtype=np.float32)
    ordered[0] = pts[np.argmin(s)]   # top-left
    ordered[2] = pts[np.argmax(s)]   # bottom-right
    ordered[1] = pts[np.argmin(d)]   # top-right
    ordered[3] = pts[np.argmax(d)]   # bottom-left
    return ordered


def warp_card(img: np.ndarray, corners: np.ndarray) -> Image.Image:
    """
    Warp detected quad to canonical 600x825 card image.

    Handles orientation: if the card is landscape, rotates it.

    Args:
        img: RGB image as numpy array
        corners: 4x2 float32 array, ordered TL/TR/BR/BL

    Returns:
        Perspective-corrected card as PIL Image (600x825)
    """
    ordered = corners.copy()

    # Check if we need to rotate (card detected in landscape)
    top_edge = np.linalg.norm(ordered[1] - ordered[0])
    left_edge = np.linalg.norm(ordered[3] - ordered[0])

    if top_edge > left_edge * 1.1:
        # Card is landscape — rotate corners by 1 position
        ordered = np.roll(ordered, -1, axis=0)

    dst = np.array(
        [[0, 0], [CARD_W, 0], [CARD_W, CARD_H], [0, CARD_H]],
        dtype=np.float32,
    )
    M = cv2.getPerspectiveTransform(ordered, dst)
    warped = cv2.warpPerspective(img, M, (CARD_W, CARD_H), flags=cv2.INTER_LANCZOS4)
    return Image.fromarray(warped)


def visualize_detection(
    image: Image.Image,
    result: DetectionResult,
) -> Image.Image:
    """
    Draw detection results on the original image for debugging.

    Returns annotated image showing:
    - Detected quad (green if found, red if fallback)
    - Corner points numbered 0-3
    - Method and confidence label
    """
    img = np.array(image.convert("RGB")).copy()

    color = (0, 255, 0) if result.card_found else (0, 0, 255)
    pts = result.corners.astype(np.int32)

    # Draw quad
    cv2.polylines(img, [pts], True, color, 3)

    # Draw corners
    for i, pt in enumerate(pts):
        cv2.circle(img, tuple(pt), 8, (255, 255, 0), -1)
        cv2.putText(
            img, str(i), (pt[0] + 10, pt[1] - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2,
        )

    # Label
    label = f"{result.method} ({result.confidence:.2f})"
    cv2.putText(
        img, label, (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2,
    )

    return Image.fromarray(img)


# ------------------------------------------------------------------
# Factory function
# ------------------------------------------------------------------

def get_detector(backend: str = "auto"):
    """
    Create a card detector with the specified backend.

    Args:
        backend: "auto" (try DocTR, then YOLO, fallback to OpenCV),
                 "doctr", "yolo", or "opencv"

    Returns:
        DocTRCardDetector, YOLOCardDetector, or CardDetector instance
    """
    if backend == "opencv":
        return CardDetector()

    if backend in ("doctr", "auto"):
        try:
            from src.doctr_detector import DocTRCardDetector
            detector = DocTRCardDetector()
            return detector
        except (ImportError, Exception) as e:
            if backend == "doctr":
                raise
            print(f"DocTR detector not available ({e}), trying YOLO.")

    if backend in ("yolo", "auto"):
        try:
            from src.yolo_card_detector import YOLOCardDetector
            detector = YOLOCardDetector()
            print(f"YOLO card detector loaded.")
            return detector
        except (ImportError, FileNotFoundError, Exception) as e:
            if backend == "yolo":
                raise
            print(f"YOLO detector not available ({e}), using OpenCV fallback.")
            return CardDetector()

    raise ValueError(f"Unknown detector backend: {backend}")


class CardDetector:
    """Detect and extract a Pokemon card from a photo."""

    # --- Tuning parameters ---
    MIN_AREA_RATIO = 0.02        # Card must be ≥2% of image area
    ASPECT_TOLERANCE = 0.20      # Allow ±20% deviation from ideal aspect

    def detect(self, image: Image.Image) -> DetectionResult:
        """
        Detect a card in the image and return the corrected card.

        Tries contour detection first, then Hough lines, then fallback.
        Always returns a DetectionResult with a warped image.
        """
        # Skip detection for already-cropped card images
        pt = check_passthrough(image)
        if pt is not None:
            return pt

        img = np.array(image.convert("RGB"))

        # Strategy 1: Contour-based (multi-preprocessing)
        result = self._detect_contour(img)
        if result.card_found and result.confidence >= 0.5:
            result.warped = self._warp(img, result.corners)
            return result

        # Strategy 2: Hough-line-based
        result_hough = self._detect_hough(img)
        if result_hough.card_found:
            if result_hough.confidence > result.confidence:
                result_hough.warped = self._warp(img, result_hough.corners)
                return result_hough

        # If contour found something (even low confidence), use it
        if result.card_found:
            result.warped = self._warp(img, result.corners)
            return result

        # Strategy 3: Fallback — assume full image is the card
        return self._fallback(image)

    # ------------------------------------------------------------------
    # Strategy 1: Contour detection
    # ------------------------------------------------------------------

    def _detect_contour(self, img: np.ndarray) -> DetectionResult:
        """
        Find the largest quadrilateral contour with card-like aspect ratio.

        Uses multiple preprocessing strategies:
        1. Adaptive Canny (auto-threshold from median)
        2. Multi-scale blur + fixed Canny
        3. Otsu threshold (for high-contrast card borders)
        """
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        h, w = gray.shape
        img_area = h * w

        candidates = []

        # Generate multiple edge maps with different strategies
        edge_maps = self._multi_edge_detect(gray)

        for edges in edge_maps:
            contours, _ = cv2.findContours(
                edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area < img_area * self.MIN_AREA_RATIO:
                    continue

                peri = cv2.arcLength(cnt, True)
                for eps_mult in (0.015, 0.02, 0.03, 0.04, 0.05):
                    approx = cv2.approxPolyDP(cnt, eps_mult * peri, True)
                    if len(approx) == 4:
                        pts = approx.reshape(4, 2).astype(np.float32)
                        score = self._score_quad(pts, img_area)
                        if score > 0:
                            candidates.append((score, pts))
                        break

        if not candidates:
            return DetectionResult(
                corners=self._image_corners(img),
                confidence=0.0,
                method="contour",
                card_found=False,
            )

        # Best candidate — refine corners to subpixel accuracy
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_pts = candidates[0]

        # Subpixel corner refinement
        refined = self._refine_corners(gray, best_pts)
        ordered = self._order_corners(refined)

        return DetectionResult(
            corners=ordered,
            confidence=min(best_score, 1.0),
            method="contour",
            card_found=True,
        )

    @staticmethod
    def _multi_edge_detect(gray: np.ndarray) -> list[np.ndarray]:
        """Generate edge maps with multiple preprocessing strategies."""
        edges_list = []
        h, w = gray.shape

        # Morphology kernel size scales with image
        k = max(3, min(7, min(w, h) // 200))
        if k % 2 == 0:
            k += 1
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))

        # Strategy 1: Adaptive Canny (threshold from median)
        for ksize in (3, 5, 7):
            blurred = cv2.GaussianBlur(gray, (ksize, ksize), 0)
            med = np.median(blurred)
            lo = int(max(0, 0.5 * med))
            hi = int(min(255, 1.3 * med))
            edges = cv2.Canny(blurred, lo, hi)
            edges = cv2.dilate(edges, kernel, iterations=2)
            edges = cv2.erode(edges, kernel, iterations=1)
            edges_list.append(edges)

        # Strategy 2: Otsu threshold → edges (good for card border vs solid bg)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        edges_otsu = cv2.Canny(otsu, 50, 150)
        edges_otsu = cv2.dilate(edges_otsu, kernel, iterations=2)
        edges_otsu = cv2.erode(edges_otsu, kernel, iterations=1)
        edges_list.append(edges_otsu)

        # Strategy 3: CLAHE + Canny (for low contrast scenes)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        blurred_e = cv2.GaussianBlur(enhanced, (5, 5), 0)
        med_e = np.median(blurred_e)
        edges_clahe = cv2.Canny(blurred_e, int(0.5 * med_e), int(1.3 * med_e))
        edges_clahe = cv2.dilate(edges_clahe, kernel, iterations=2)
        edges_clahe = cv2.erode(edges_clahe, kernel, iterations=1)
        edges_list.append(edges_clahe)

        return edges_list

    @staticmethod
    def _refine_corners(gray: np.ndarray, pts: np.ndarray) -> np.ndarray:
        """Refine corner positions to subpixel accuracy."""
        criteria = (
            cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.01
        )
        try:
            refined = cv2.cornerSubPix(
                gray, pts.copy(), (5, 5), (-1, -1), criteria
            )
            return refined
        except cv2.error:
            return pts

    # ------------------------------------------------------------------
    # Strategy 2: Hough line detection
    # ------------------------------------------------------------------

    def _detect_hough(self, img: np.ndarray) -> DetectionResult:
        """
        Detect card via Hough lines.

        Useful when the contour is broken (e.g. fingers covering card edges).
        Finds dominant line groups, computes intersections, picks best quad.
        """
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        h, w = gray.shape
        img_area = h * w

        # Use just 2 edge maps (adaptive Canny + CLAHE) to keep speed <200ms
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        med = np.median(blurred)
        edges1 = cv2.Canny(blurred, int(max(0, 0.5 * med)), int(min(255, 1.3 * med)))

        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        blurred_e = cv2.GaussianBlur(enhanced, (5, 5), 0)
        med_e = np.median(blurred_e)
        edges2 = cv2.Canny(blurred_e, int(0.5 * med_e), int(1.3 * med_e))

        best_result = DetectionResult(
            corners=self._image_corners(img),
            confidence=0.0,
            method="hough",
            card_found=False,
        )

        for edges in (edges1, edges2):
            for thresh, min_len_frac in ((80, 0.10), (50, 0.07)):
                lines = cv2.HoughLinesP(
                    edges, rho=1, theta=np.pi / 180, threshold=thresh,
                    minLineLength=min(w, h) * min_len_frac,
                    maxLineGap=min(w, h) * 0.05,
                )

                if lines is None or len(lines) < 4:
                    continue

                result = self._hough_lines_to_quad(lines, w, h, img_area)
                if result is not None and result.confidence > best_result.confidence:
                    best_result = result
                    if best_result.confidence >= 0.6:
                        return best_result  # Good enough, stop early

        return best_result

    def _hough_lines_to_quad(
        self, lines: np.ndarray, w: int, h: int, img_area: float
    ) -> Optional[DetectionResult]:
        """Try to form a card quad from detected Hough lines."""
        # Group lines by angle into ~horizontal and ~vertical
        h_lines = []
        v_lines = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180

            if angle < 35 or angle > 145:
                h_lines.append((x1, y1, x2, y2))
            elif 55 < angle < 125:
                v_lines.append((x1, y1, x2, y2))

        if len(h_lines) < 2 or len(v_lines) < 2:
            return None

        # Cluster & pick edge pairs
        top, bottom = self._pick_edge_pair(h_lines, axis="h", img_size=h)
        left, right = self._pick_edge_pair(v_lines, axis="v", img_size=w)

        if top is None or left is None:
            return None

        # Compute 4 intersection points
        corners = []
        for h_line in (top, bottom):
            for v_line in (left, right):
                pt = self._line_intersection(h_line[:4], v_line[:4])
                if pt is not None:
                    corners.append(pt)

        if len(corners) != 4:
            return None

        pts = np.array(corners, dtype=np.float32)
        pts[:, 0] = np.clip(pts[:, 0], 0, w - 1)
        pts[:, 1] = np.clip(pts[:, 1], 0, h - 1)

        score = self._score_quad(pts, img_area)
        if score <= 0:
            return None

        ordered = self._order_corners(pts)
        return DetectionResult(
            corners=ordered,
            confidence=min(score * 0.8, 1.0),
            method="hough",
            card_found=True,
        )

    def _pick_edge_pair(
        self, lines: list, axis: str, img_size: int
    ) -> tuple:
        """
        From a group of parallel lines, pick two that likely form
        opposite edges of the card.
        """
        if len(lines) < 2:
            return None, None

        # Sort by position (y for horizontal, x for vertical)
        if axis == "h":
            lines.sort(key=lambda l: (l[1] + l[3]) / 2)
        else:
            lines.sort(key=lambda l: (l[0] + l[2]) / 2)

        # Card must span at least 10% of image (lower threshold for small cards)
        min_sep = img_size * 0.10

        first = lines[0]
        last = lines[-1]

        if axis == "h":
            sep = abs((last[1] + last[3]) / 2 - (first[1] + first[3]) / 2)
        else:
            sep = abs((last[0] + last[2]) / 2 - (first[0] + first[2]) / 2)

        if sep < min_sep:
            return None, None

        return first, last

    @staticmethod
    def _line_intersection(
        line1: tuple, line2: tuple
    ) -> Optional[tuple[float, float]]:
        """Compute intersection of two lines given as (x1,y1,x2,y2)."""
        x1, y1, x2, y2 = line1
        x3, y3, x4, y4 = line2

        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-6:
            return None  # Parallel

        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        px = x1 + t * (x2 - x1)
        py = y1 + t * (y2 - y1)
        return (px, py)

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def _fallback(self, image: Image.Image) -> DetectionResult:
        """Assume the entire image is the card."""
        warped = image.resize((CARD_W, CARD_H), Image.LANCZOS)
        w, h = image.size
        corners = np.array(
            [[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32
        )
        return DetectionResult(
            corners=corners,
            confidence=0.0,
            method="fallback",
            card_found=False,
            warped=warped,
        )

    # ------------------------------------------------------------------
    # Scoring & geometry helpers
    # ------------------------------------------------------------------

    def _score_quad(
        self, pts: np.ndarray, img_area: float,
        img_shape: tuple[int, int] | None = None,
    ) -> float:
        """
        Score a quadrilateral on how card-like it is.

        Criteria:
        - Aspect ratio close to 63:88
        - Reasonable size (not too small / large)
        - Convexity
        - Angles close to 90 degrees

        Returns 0.0 if invalid, up to ~1.0 for perfect card shape.
        """
        # Must be convex
        if not cv2.isContourConvex(pts.reshape(-1, 1, 2).astype(np.int32)):
            return 0.0

        area = cv2.contourArea(pts.reshape(-1, 1, 2).astype(np.int32))
        if area < img_area * self.MIN_AREA_RATIO:
            return 0.0

        area_ratio = area / img_area

        # Reject if quad covers almost the entire image
        if area_ratio > 0.92:
            return 0.0

        # Aspect ratio check via minAreaRect
        rect = cv2.minAreaRect(pts.reshape(-1, 1, 2).astype(np.int32))
        rw, rh = rect[1]
        if rw == 0 or rh == 0:
            return 0.0

        aspect = min(rw, rh) / max(rw, rh)
        aspect_diff = abs(aspect - CARD_ASPECT)
        if aspect_diff > self.ASPECT_TOLERANCE:
            return 0.0

        # Score components
        aspect_score = 1.0 - (aspect_diff / self.ASPECT_TOLERANCE)

        # Area score: prefer larger detections (card fills more of image)
        if area_ratio > 0.85:
            area_score = 0.5
        else:
            area_score = min(area_ratio * 3, 1.0)

        # Angle score: corners should be close to 90 degrees
        ordered = self._order_corners(pts)
        angle_score = self._angle_score(ordered)

        return aspect_score * 0.4 + area_score * 0.3 + angle_score * 0.3

    @staticmethod
    def _angle_score(corners: np.ndarray) -> float:
        """Score how close the quad angles are to 90 degrees."""
        scores = []
        for i in range(4):
            p1 = corners[i]
            p2 = corners[(i + 1) % 4]
            p3 = corners[(i - 1) % 4]

            v1 = p2 - p1
            v2 = p3 - p1
            norm1 = np.linalg.norm(v1)
            norm2 = np.linalg.norm(v2)
            if norm1 < 1e-6 or norm2 < 1e-6:
                return 0.0

            cos_angle = np.dot(v1, v2) / (norm1 * norm2)
            cos_angle = np.clip(cos_angle, -1, 1)
            angle = np.degrees(np.arccos(cos_angle))
            # Ideal is 90 degrees
            scores.append(1.0 - abs(angle - 90) / 90)

        return max(np.mean(scores), 0.0)

    @staticmethod
    def _order_corners(pts: np.ndarray) -> np.ndarray:
        """Order 4 points as: top-left, top-right, bottom-right, bottom-left."""
        return order_corners(pts)

    @staticmethod
    def _image_corners(img: np.ndarray) -> np.ndarray:
        """Return corners of the full image."""
        h, w = img.shape[:2]
        return np.array(
            [[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32
        )

    # ------------------------------------------------------------------
    # Perspective correction
    # ------------------------------------------------------------------

    def _warp(self, img: np.ndarray, corners: np.ndarray) -> Image.Image:
        """Warp detected quad to canonical 600x825 card image."""
        return warp_card(img, corners)

    # ------------------------------------------------------------------
    # Visualization (for debugging / testing)
    # ------------------------------------------------------------------

    def visualize(
        self,
        image: Image.Image,
        result: DetectionResult,
    ) -> Image.Image:
        """Draw detection results on the original image (delegates to module-level function)."""
        return visualize_detection(image, result)
