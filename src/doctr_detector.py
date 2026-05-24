"""
DocTR-based card detector using pretrained DBNet.

Detects text regions on the card → convex hull → minAreaRect → 4 corners → warp.
More robust than YOLO-pose on real photos (plastic sleeves, glare, angles).

Usage:
    from src.doctr_detector import DocTRCardDetector
    detector = DocTRCardDetector()
    result = detector.detect(pil_image)
"""

from __future__ import annotations

import os
from typing import Optional

import cv2
import numpy as np
from PIL import Image

from src.card_detector import (
    CARD_H,
    CARD_W,
    DetectionResult,
    check_passthrough,
    order_corners,
    warp_card,
)

# Ensure PyTorch backend for DocTR
os.environ.setdefault("USE_TORCH", "1")


class DocTRCardDetector:
    """Card detector using DocTR's pretrained DBNet text detector."""

    def __init__(self, arch: str = "db_resnet50"):
        from doctr.models import detection_predictor

        self._model = detection_predictor(arch=arch, pretrained=True)
        self._arch = arch
        print(f"DocTR detector ready ({arch})")

    def detect(self, image: Image.Image) -> DetectionResult:
        """Detect a card by finding text regions and computing their bounding quad."""
        # Passthrough for already-cropped images
        pt = check_passthrough(image)
        if pt is not None:
            return pt

        img_np = np.array(image.convert("RGB"))
        h, w = img_np.shape[:2]

        # DocTR expects [0,1] float RGB
        doc_input = img_np[:, :, :3].astype(np.float32) / 255.0

        try:
            result = self._model([doc_input])
        except Exception:
            return self._fallback(image)

        # result is [{"words": [array([x1,y1,x2,y2,conf]), ...]}]
        page = result[0]
        words = page.get("words", [])

        if len(words) < 3:
            return self._fallback(image)

        # Collect all text box corners (normalized → pixel coords)
        all_points = []
        confidences = []
        for word in words:
            x1, y1, x2, y2 = word[:4]
            conf = word[4] if len(word) > 4 else 0.5
            confidences.append(conf)
            all_points.extend([
                [x1 * w, y1 * h],
                [x2 * w, y1 * h],
                [x2 * w, y2 * h],
                [x1 * w, y2 * h],
            ])

        all_points = np.array(all_points, dtype=np.float32)

        # Convex hull → minimum area rectangle → 4 ordered corners
        hull = cv2.convexHull(all_points).reshape(-1, 2)
        rect = cv2.minAreaRect(hull)
        box = cv2.boxPoints(rect)
        corners = order_corners(box)

        # Expand slightly — text is inside the card border
        center = corners.mean(axis=0)
        corners = center + (corners - center) * 1.05
        corners = np.clip(corners, [0, 0], [w - 1, h - 1]).astype(np.float32)

        warped = warp_card(img_np, corners)
        avg_conf = float(np.mean(confidences))

        return DetectionResult(
            corners=corners,
            confidence=avg_conf,
            method="doctr",
            card_found=True,
            warped=warped,
        )

    def _fallback(self, image: Image.Image) -> DetectionResult:
        """No text detected — resize to card dimensions as fallback."""
        warped = image.resize((CARD_W, CARD_H), Image.LANCZOS)
        w, h = image.size
        corners = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
        return DetectionResult(
            corners=corners,
            confidence=0.0,
            method="doctr_fallback",
            card_found=False,
            warped=warped,
        )
