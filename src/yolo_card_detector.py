"""
YOLO-pose based card detector using ONNX Runtime.

Detects a card in an image and predicts 4 corner keypoints (TL, TR, BR, BL)
in a single forward pass. Drop-in replacement for CardDetector.

Model: YOLOv8n-pose trained on synthetic card dataset.
Inference: ONNX Runtime (no ultralytics dependency in production).

Usage:
    from src.yolo_card_detector import YOLOCardDetector

    detector = YOLOCardDetector()  # auto-finds model
    result = detector.detect(pil_image)
    # result.corners, result.warped, result.confidence, result.method
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image

from src.card_detector import (
    CARD_H,
    CARD_W,
    DetectionResult,
    order_corners,
    visualize_detection,
    warp_card,
)

# Default model paths (checked in order)
MODEL_PATHS = [
    Path("models/yolo_card/card_detector.onnx"),
    Path("models/yolo_card/best.onnx"),
]

# Inference parameters
INPUT_SIZE = 640
CONF_THRESHOLD = 0.3      # Minimum detection confidence
KPT_CONF_THRESHOLD = 0.2  # Minimum keypoint visibility score


class YOLOCardDetector:
    """
    YOLO-pose card detector with ONNX Runtime inference.

    Predicts bounding box + 4 corner keypoints in one forward pass.
    Falls back to OpenCV CardDetector if confidence is too low.
    """

    def __init__(self, model_path: Optional[str] = None):
        """
        Initialize the YOLO card detector.

        Args:
            model_path: Path to .onnx model file. If None, searches default locations.

        Raises:
            FileNotFoundError: If no model file is found.
            ImportError: If onnxruntime is not installed.
        """
        try:
            import onnxruntime as ort
        except ImportError:
            raise ImportError(
                "onnxruntime is required for YOLO detector. "
                "Install with: pip install onnxruntime"
            )

        # Find model
        if model_path:
            self._model_path = Path(model_path)
        else:
            self._model_path = None
            for p in MODEL_PATHS:
                if p.exists():
                    self._model_path = p
                    break

        if self._model_path is None or not self._model_path.exists():
            raise FileNotFoundError(
                f"YOLO model not found. Expected at: {MODEL_PATHS[0]}\n"
                "Train and export a model first:\n"
                "  1. py -3.11 scripts/generate_yolo_dataset.py\n"
                "  2. py -3.11 scripts/train_yolo_card.py\n"
                "  3. py -3.11 scripts/export_yolo_onnx.py"
            )

        # Create ONNX session
        providers = ["CPUExecutionProvider"]
        # Try CUDA if available
        if "CUDAExecutionProvider" in ort.get_available_providers():
            providers.insert(0, "CUDAExecutionProvider")

        self._session = ort.InferenceSession(
            str(self._model_path), providers=providers
        )

        # Get model input/output info
        self._input_name = self._session.get_inputs()[0].name
        self._input_shape = self._session.get_inputs()[0].shape
        self._output_names = [o.name for o in self._session.get_outputs()]

        print(f"YOLO detector: {self._model_path.name} "
              f"(input: {self._input_shape}, providers: {self._session.get_providers()})")

    def detect(self, image: Image.Image) -> DetectionResult:
        """
        Detect a card in the image using YOLO-pose.

        Args:
            image: Input PIL image (any size).

        Returns:
            DetectionResult with corners, warped card, confidence, method="yolo".
        """
        img_rgb = np.array(image.convert("RGB"))
        orig_h, orig_w = img_rgb.shape[:2]

        # Preprocess: letterbox to 640x640
        input_tensor, scale, pad_x, pad_y = self._preprocess(img_rgb)

        # ONNX inference
        outputs = self._session.run(self._output_names, {self._input_name: input_tensor})

        # Parse predictions
        predictions = outputs[0]  # shape: (1, num_detections, 5 + num_classes + num_kpts*3)

        # Find best detection
        best = self._parse_predictions(predictions, scale, pad_x, pad_y, orig_w, orig_h)

        if best is None:
            # No card found — return fallback
            return self._fallback(image)

        confidence, corners = best

        if confidence < CONF_THRESHOLD:
            return self._fallback(image)

        # Order corners consistently
        ordered = order_corners(corners)

        # Warp to canonical card image
        warped = warp_card(img_rgb, ordered)

        return DetectionResult(
            corners=ordered,
            confidence=float(confidence),
            method="yolo",
            card_found=True,
            warped=warped,
        )

    def visualize(self, image: Image.Image, result: DetectionResult) -> Image.Image:
        """Draw detection results (delegates to module-level function)."""
        return visualize_detection(image, result)

    # ------------------------------------------------------------------
    # Preprocessing
    # ------------------------------------------------------------------

    def _preprocess(
        self, img: np.ndarray
    ) -> tuple[np.ndarray, float, float, float]:
        """
        Letterbox resize + normalize for YOLO input.

        Returns:
            (input_tensor, scale, pad_x, pad_y)
            - input_tensor: (1, 3, 640, 640) float32
            - scale: resize scale factor
            - pad_x, pad_y: padding offsets
        """
        h, w = img.shape[:2]

        # Compute scale to fit in INPUT_SIZE
        scale = min(INPUT_SIZE / w, INPUT_SIZE / h)
        new_w = int(w * scale)
        new_h = int(h * scale)

        # Resize
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        # Pad to square
        pad_x = (INPUT_SIZE - new_w) / 2
        pad_y = (INPUT_SIZE - new_h) / 2
        top = int(pad_y)
        bottom = INPUT_SIZE - new_h - top
        left = int(pad_x)
        right = INPUT_SIZE - new_w - left

        padded = cv2.copyMakeBorder(
            resized, top, bottom, left, right,
            cv2.BORDER_CONSTANT, value=(114, 114, 114),
        )

        # HWC -> CHW, normalize 0-1, add batch dim
        blob = padded.astype(np.float32) / 255.0
        blob = blob.transpose(2, 0, 1)  # CHW
        blob = blob[np.newaxis, ...]    # NCHW

        return blob, scale, pad_x, pad_y

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    def _parse_predictions(
        self,
        predictions: np.ndarray,
        scale: float,
        pad_x: float,
        pad_y: float,
        orig_w: int,
        orig_h: int,
    ) -> Optional[tuple[float, np.ndarray]]:
        """
        Parse YOLO output to find the best card detection.

        YOLOv8-pose output shape: (1, N, 5 + nc + nk*3)
        For our model: (1, N, 5 + 1 + 4*3) = (1, N, 18)
          - [0:4] = bbox (cx, cy, w, h) in input coords
          - [4] = objectness score
          - [5] = class score (single class: card)
          - [6:18] = 4 keypoints * (x, y, visibility)

        Actually YOLOv8 format is transposed: (1, 18, N)
        We need to handle both formats.

        Returns:
            (confidence, corners_4x2) or None
        """
        pred = predictions[0]  # Remove batch dim

        # Determine format: (N, 18) or (18, N)
        if pred.shape[0] < pred.shape[1]:
            # (18, N) format — transpose to (N, 18)
            pred = pred.T

        if pred.shape[0] == 0:
            return None

        # Expected columns: cx, cy, w, h, conf, cls_score, kx1, ky1, kv1, ..., kx4, ky4, kv4
        # But YOLOv8 pose output might be: cx, cy, w, h, cls_score, kx1, ky1, kv1, ..., kx4, ky4, kv4
        # (no separate objectness — class score IS the confidence)
        num_cols = pred.shape[1]

        if num_cols == 17:
            # Format: cx, cy, w, h, cls_conf, kx1, ky1, kv1, ..., kx4, ky4, kv4
            box_conf = pred[:, 4]
            kpt_start = 5
        elif num_cols == 18:
            # Format: cx, cy, w, h, obj_conf, cls_conf, kx1, ky1, kv1, ..., kx4, ky4, kv4
            box_conf = pred[:, 4] * pred[:, 5]
            kpt_start = 6
        else:
            # Try to figure it out: should be 4 (box) + conf + 4*3 (kpts) = 17 or 18
            # If more classes, skip
            n_kpt_cols = 4 * 3  # 12
            n_box = 4
            n_extra = num_cols - n_box - n_kpt_cols
            if n_extra == 1:
                box_conf = pred[:, 4]
                kpt_start = 5
            elif n_extra == 2:
                box_conf = pred[:, 4] * pred[:, 5]
                kpt_start = 6
            else:
                return None

        # Filter by confidence
        mask = box_conf >= CONF_THRESHOLD
        if not mask.any():
            # Try lower threshold to at least return something
            mask = box_conf >= (CONF_THRESHOLD * 0.5)
            if not mask.any():
                return None

        filtered = pred[mask]
        confs = box_conf[mask]

        # Pick highest confidence
        best_idx = np.argmax(confs)
        best_conf = float(confs[best_idx])
        best_pred = filtered[best_idx]

        # Extract keypoints
        kpts = best_pred[kpt_start:kpt_start + 12].reshape(4, 3)  # (x, y, visibility)

        # Check keypoint visibility
        kpt_visible = kpts[:, 2] >= KPT_CONF_THRESHOLD
        if kpt_visible.sum() < 3:
            # Not enough visible keypoints — can't determine corners
            # Fall back to bbox corners if at least the box is confident
            if best_conf >= CONF_THRESHOLD:
                cx, cy, bw, bh = best_pred[:4]
                corners = np.array([
                    [cx - bw / 2, cy - bh / 2],
                    [cx + bw / 2, cy - bh / 2],
                    [cx + bw / 2, cy + bh / 2],
                    [cx - bw / 2, cy + bh / 2],
                ], dtype=np.float32)
                # Unmap from letterbox to original
                corners = self._unmap_coords(corners, scale, pad_x, pad_y, orig_w, orig_h)
                return (best_conf * 0.5, corners)  # Lower confidence for bbox-only
            return None

        # Get corner coordinates
        corners = kpts[:, :2].astype(np.float32)

        # Unmap from letterbox coordinates to original image coordinates
        corners = self._unmap_coords(corners, scale, pad_x, pad_y, orig_w, orig_h)

        return (best_conf, corners)

    def _unmap_coords(
        self,
        coords: np.ndarray,
        scale: float,
        pad_x: float,
        pad_y: float,
        orig_w: int,
        orig_h: int,
    ) -> np.ndarray:
        """Unmap coordinates from letterboxed input back to original image."""
        # Remove padding
        coords[:, 0] = (coords[:, 0] - pad_x) / scale
        coords[:, 1] = (coords[:, 1] - pad_y) / scale

        # Clip to image bounds
        coords[:, 0] = np.clip(coords[:, 0], 0, orig_w - 1)
        coords[:, 1] = np.clip(coords[:, 1], 0, orig_h - 1)

        return coords

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def _fallback(self, image: Image.Image) -> DetectionResult:
        """Assume the entire image is the card (same as OpenCV fallback)."""
        warped = image.resize((CARD_W, CARD_H), Image.LANCZOS)
        w, h = image.size
        corners = np.array(
            [[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32
        )
        return DetectionResult(
            corners=corners,
            confidence=0.0,
            method="yolo_fallback",
            card_found=False,
            warped=warped,
        )
