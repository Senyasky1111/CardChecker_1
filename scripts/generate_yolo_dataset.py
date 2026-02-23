"""
Generate synthetic YOLO-pose training dataset for card detection.

Takes real card images from data/cardmarket/images/ and composites them
onto procedural backgrounds with random transformations (rotation, perspective,
scale, position). Ground-truth corners are computed automatically from the
known transformation.

Output format: YOLOv8-pose
  Label: <cls> <cx> <cy> <w> <h> <x1> <y1> <v1> ... <x4> <y4> <v4>
  All values normalized 0-1.  Keypoints: TL, TR, BR, BL. v=2 (visible).

Usage:
    py -3.11 scripts/generate_yolo_dataset.py [--num-train 5000] [--num-val 500]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from pathlib import Path
from typing import Optional

import albumentations as A
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# ── Config ───────────────────────────────────────────────────────────
CANVAS_SIZE = 640        # YOLO input size
CARD_ASPECT = 63 / 88   # width / height
MIN_CARD_SCALE = 0.25    # card height as fraction of canvas
MAX_CARD_SCALE = 0.85
MAX_ROTATION_DEG = 45
MAX_PERSPECTIVE = 0.35   # perspective warp strength

IMAGES_DIR = Path("data/cardmarket/images")
OUTPUT_DIR = Path("data/yolo_card_dataset")


# ── Procedural background generators ────────────────────────────────

def bg_solid(size: int) -> np.ndarray:
    """Random solid color background."""
    color = [random.randint(0, 255) for _ in range(3)]
    return np.full((size, size, 3), color, dtype=np.uint8)


def bg_gradient(size: int) -> np.ndarray:
    """Random gradient background."""
    c1 = np.array([random.randint(0, 255) for _ in range(3)], dtype=np.float32)
    c2 = np.array([random.randint(0, 255) for _ in range(3)], dtype=np.float32)

    if random.random() < 0.5:
        # Vertical gradient
        t = np.linspace(0, 1, size).reshape(-1, 1, 1)
        img = (c1 * (1 - t) + c2 * t).astype(np.uint8)
        img = np.broadcast_to(img, (size, size, 3)).copy()
    else:
        # Horizontal gradient
        t = np.linspace(0, 1, size).reshape(1, -1, 1)
        img = (c1 * (1 - t) + c2 * t).astype(np.uint8)
        img = np.broadcast_to(img, (size, size, 3)).copy()

    return img


def bg_noise(size: int) -> np.ndarray:
    """Random noise background."""
    base = np.random.randint(0, 255, (size, size, 3), dtype=np.uint8)
    # Optionally blur for texture
    if random.random() < 0.5:
        ksize = random.choice([3, 5, 7])
        base = cv2.GaussianBlur(base, (ksize, ksize), 0)
    return base


def bg_pattern(size: int) -> np.ndarray:
    """Checkerboard / stripe pattern background."""
    img = np.zeros((size, size, 3), dtype=np.uint8)
    c1 = [random.randint(0, 200) for _ in range(3)]
    c2 = [random.randint(50, 255) for _ in range(3)]
    block = random.randint(20, 80)

    for y in range(0, size, block):
        for x in range(0, size, block):
            color = c1 if ((y // block) + (x // block)) % 2 == 0 else c2
            img[y:y + block, x:x + block] = color

    return img


def bg_wood_texture(size: int) -> np.ndarray:
    """Simulated wood/table texture."""
    base_hue = random.randint(10, 30)
    base_sat = random.randint(80, 180)
    base_val = random.randint(100, 200)

    img_hsv = np.zeros((size, size, 3), dtype=np.uint8)
    img_hsv[:, :, 0] = base_hue
    img_hsv[:, :, 1] = base_sat
    img_hsv[:, :, 2] = base_val

    # Add grain lines
    noise = np.random.randn(size, size).astype(np.float32) * 15
    noise = cv2.GaussianBlur(noise, (1, 31), 0)  # Horizontal grain
    img_hsv[:, :, 2] = np.clip(img_hsv[:, :, 2].astype(np.float32) + noise, 0, 255).astype(np.uint8)

    img = cv2.cvtColor(img_hsv, cv2.COLOR_HSV2RGB)
    return img


def generate_background(size: int) -> np.ndarray:
    """Pick a random background type."""
    generators = [bg_solid, bg_gradient, bg_noise, bg_pattern, bg_wood_texture]
    weights = [0.15, 0.2, 0.2, 0.15, 0.3]  # Wood is most common (table scenarios)
    gen = random.choices(generators, weights=weights, k=1)[0]
    return gen(size)


# ── Card augmentation pipeline (Albumentations) ─────────────────────

card_augment = A.Compose([
    A.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.3, hue=0.05, p=0.8),
    A.OneOf([
        A.GaussianBlur(blur_limit=(3, 5), p=1),
        A.MotionBlur(blur_limit=(3, 7), p=1),
    ], p=0.3),
    A.GaussNoise(std_range=(0.01, 0.05), p=0.3),
    A.ImageCompression(quality_range=(50, 95), p=0.3),
], p=1.0)

# Post-composite augmentation (applied to final image)
composite_augment = A.Compose([
    A.ColorJitter(brightness=0.15, contrast=0.15, saturation=0.1, hue=0.02, p=0.5),
    A.GaussNoise(std_range=(0.005, 0.02), p=0.3),
    A.ImageCompression(quality_range=(60, 95), p=0.3),
], p=1.0)


# ── Occlusion simulation (fingers, shadows) ─────────────────────────

def add_finger_occlusion(canvas: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """Simulate finger(s) partially covering card edges."""
    if random.random() > 0.3:  # 30% chance of finger occlusion
        return canvas

    h, w = canvas.shape[:2]
    n_fingers = random.randint(1, 3)

    for _ in range(n_fingers):
        # Pick a random edge of the card
        edge_idx = random.randint(0, 3)
        p1 = corners[edge_idx]
        p2 = corners[(edge_idx + 1) % 4]

        # Point along the edge
        t = random.uniform(0.2, 0.8)
        base = p1 + t * (p2 - p1)

        # Finger extends outward from edge
        edge_vec = p2 - p1
        normal = np.array([-edge_vec[1], edge_vec[0]])
        normal = normal / (np.linalg.norm(normal) + 1e-6)

        # Finger dimensions
        finger_len = random.randint(40, 100)
        finger_width = random.randint(15, 35)

        # Finger color (skin tones)
        skin_r = random.randint(160, 240)
        skin_g = random.randint(120, 200)
        skin_b = random.randint(80, 160)

        # Draw ellipse for finger
        center = (int(base[0]), int(base[1]))
        angle = math.degrees(math.atan2(normal[1], normal[0]))
        axes = (finger_len // 2, finger_width // 2)

        cv2.ellipse(canvas, center, axes, angle, 0, 360, (skin_r, skin_g, skin_b), -1)

    return canvas


def add_shadow(canvas: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """Add a subtle shadow under/around the card."""
    if random.random() > 0.5:
        return canvas

    # Shift corners slightly for shadow
    offset = np.array([random.randint(3, 10), random.randint(3, 10)], dtype=np.float32)
    shadow_corners = (corners + offset).astype(np.int32)

    overlay = canvas.copy()
    cv2.fillConvexPoly(overlay, shadow_corners, (0, 0, 0))

    alpha = random.uniform(0.1, 0.3)
    canvas = cv2.addWeighted(overlay, alpha, canvas, 1 - alpha, 0)
    return canvas


# ── Sleeve / toploader simulation ───────────────────────────────────

def add_sleeve_effect(card_img: np.ndarray) -> np.ndarray:
    """Simulate card in a sleeve — slight glare, border."""
    if random.random() > 0.25:  # 25% chance
        return card_img

    h, w = card_img.shape[:2]

    # Add thin translucent border (sleeve edge)
    border = random.randint(2, 6)
    sleeve_color = random.choice([
        (220, 220, 230),  # Clear sleeve
        (200, 200, 210),  # Matte sleeve
        (180, 180, 200),  # Colored sleeve
    ])
    cv2.rectangle(card_img, (0, 0), (w - 1, h - 1), sleeve_color, border)

    # Add glare spot
    if random.random() < 0.4:
        cx = random.randint(w // 4, 3 * w // 4)
        cy = random.randint(h // 4, 3 * h // 4)
        radius = random.randint(30, 80)
        overlay = card_img.copy()
        cv2.circle(overlay, (cx, cy), radius, (255, 255, 255), -1)
        alpha = random.uniform(0.05, 0.15)
        card_img = cv2.addWeighted(overlay, alpha, card_img, 1 - alpha, 0)

    return card_img


# ── Core: composite card onto background ─────────────────────────────

def perspective_transform_corners(
    corners: np.ndarray, strength: float
) -> np.ndarray:
    """Apply random perspective distortion to corner points."""
    # corners: 4x2, TL TR BR BL
    w = np.linalg.norm(corners[1] - corners[0])
    h = np.linalg.norm(corners[3] - corners[0])
    max_offset = strength * min(w, h) * 0.15

    perturbed = corners.copy()
    for i in range(4):
        dx = random.uniform(-max_offset, max_offset)
        dy = random.uniform(-max_offset, max_offset)
        perturbed[i] += [dx, dy]

    return perturbed


def generate_sample(
    card_path: str,
    canvas_size: int = CANVAS_SIZE,
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """
    Generate one training sample.

    Returns:
        (canvas_rgb, corners_4x2) or None if failed.
        corners are in pixel coordinates on the canvas.
    """
    # Load card image
    try:
        card_pil = Image.open(card_path).convert("RGBA")
    except Exception:
        return None

    card_w, card_h = card_pil.size
    if card_w < 50 or card_h < 50:
        return None

    # Generate background
    canvas = generate_background(canvas_size)

    # Random card size on canvas
    scale = random.uniform(MIN_CARD_SCALE, MAX_CARD_SCALE)
    target_h = int(canvas_size * scale)
    target_w = int(target_h * CARD_ASPECT)

    # Resize card
    card_resized = card_pil.resize((target_w, target_h), Image.LANCZOS)

    # Convert to numpy for augmentation
    card_np = np.array(card_resized)

    # Split alpha if present
    if card_np.shape[2] == 4:
        card_rgb = card_np[:, :, :3]
        card_alpha = card_np[:, :, 3]
    else:
        card_rgb = card_np
        card_alpha = np.full((target_h, target_w), 255, dtype=np.uint8)

    # Apply card-level augmentation
    card_rgb = card_augment(image=card_rgb)["image"].copy()

    # Sleeve effect
    card_rgb = add_sleeve_effect(card_rgb)

    # Define source corners (of the card image)
    src_corners = np.array([
        [0, 0],
        [target_w, 0],
        [target_w, target_h],
        [0, target_h],
    ], dtype=np.float32)

    # Random rotation
    angle = random.uniform(-MAX_ROTATION_DEG, MAX_ROTATION_DEG)

    # Random position (center of card on canvas)
    # Ensure card mostly stays within canvas
    margin = int(canvas_size * 0.05)
    cx = random.randint(margin + target_w // 4, canvas_size - margin - target_w // 4)
    cy = random.randint(margin + target_h // 4, canvas_size - margin - target_h // 4)

    # Build transformation: translate to center, rotate, apply perspective
    # Step 1: Translate card so its center is at (cx, cy)
    card_center = np.array([target_w / 2, target_h / 2], dtype=np.float32)
    translated = src_corners - card_center

    # Step 2: Rotate
    rad = math.radians(angle)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    rot_matrix = np.array([[cos_a, -sin_a], [sin_a, cos_a]], dtype=np.float32)
    rotated = (rot_matrix @ translated.T).T

    # Step 3: Translate to canvas position
    dst_corners = rotated + np.array([cx, cy], dtype=np.float32)

    # Step 4: Perspective distortion
    persp_strength = random.uniform(0, MAX_PERSPECTIVE)
    dst_corners = perspective_transform_corners(dst_corners, persp_strength)

    # Compute perspective transform matrix
    M = cv2.getPerspectiveTransform(src_corners, dst_corners)

    # Warp card onto canvas
    warped_card = cv2.warpPerspective(
        card_rgb, M, (canvas_size, canvas_size),
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    warped_alpha = cv2.warpPerspective(
        card_alpha, M, (canvas_size, canvas_size),
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )

    # Add shadow before compositing
    canvas = add_shadow(canvas, dst_corners)

    # Alpha composite
    alpha_3ch = warped_alpha[:, :, np.newaxis].astype(np.float32) / 255.0
    canvas = (
        canvas.astype(np.float32) * (1 - alpha_3ch) +
        warped_card.astype(np.float32) * alpha_3ch
    ).astype(np.uint8)

    # Add finger occlusion (after card is placed)
    canvas = add_finger_occlusion(canvas, dst_corners)

    # Apply composite-level augmentation
    canvas = composite_augment(image=canvas)["image"]

    # Clip corners to canvas bounds
    dst_corners[:, 0] = np.clip(dst_corners[:, 0], 0, canvas_size - 1)
    dst_corners[:, 1] = np.clip(dst_corners[:, 1], 0, canvas_size - 1)

    return canvas, dst_corners


# ── YOLO-pose label formatting ───────────────────────────────────────

def corners_to_yolo_pose(
    corners: np.ndarray, canvas_size: int
) -> str:
    """
    Convert 4 corners to YOLO-pose format string.

    Format: <cls> <cx> <cy> <w> <h> <x1> <y1> <v1> ... <x4> <y4> <v4>
    All normalized to 0-1. cls=0. v=2 (visible).
    """
    # Bounding box from corners
    x_min = corners[:, 0].min()
    x_max = corners[:, 0].max()
    y_min = corners[:, 1].min()
    y_max = corners[:, 1].max()

    cx = (x_min + x_max) / 2 / canvas_size
    cy = (y_min + y_max) / 2 / canvas_size
    w = (x_max - x_min) / canvas_size
    h = (y_max - y_min) / canvas_size

    # Keypoints: TL, TR, BR, BL (already in this order)
    kpts = []
    for i in range(4):
        kx = corners[i, 0] / canvas_size
        ky = corners[i, 1] / canvas_size
        kpts.extend([kx, ky, 2])  # v=2 means visible

    parts = [0, cx, cy, w, h] + kpts
    return " ".join(f"{v:.6f}" if isinstance(v, float) else str(v) for v in parts)


# ── Visualization (for debugging) ────────────────────────────────────

def visualize_sample(
    image: np.ndarray, corners: np.ndarray, save_path: str
) -> None:
    """Save a debug visualization with drawn corners."""
    vis = image.copy()
    pts = corners.astype(np.int32)
    cv2.polylines(vis, [pts], True, (0, 255, 0), 2)
    for i, pt in enumerate(pts):
        cv2.circle(vis, tuple(pt), 5, (255, 0, 0), -1)
        cv2.putText(vis, str(i), (pt[0] + 5, pt[1] - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
    cv2.imwrite(save_path, cv2.cvtColor(vis, cv2.COLOR_RGB2BGR))


# ── Main generator ───────────────────────────────────────────────────

def generate_dataset(
    num_train: int = 5000,
    num_val: int = 500,
    visualize_n: int = 10,
):
    """Generate the full training + validation dataset."""
    # Collect card images
    card_files = sorted(IMAGES_DIR.glob("*.jpg")) + sorted(IMAGES_DIR.glob("*.png"))
    if not card_files:
        print(f"ERROR: No card images found in {IMAGES_DIR}")
        sys.exit(1)

    print(f"Found {len(card_files)} card images in {IMAGES_DIR}")

    # Create output directories
    for split in ("train", "val"):
        (OUTPUT_DIR / "images" / split).mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "labels" / split).mkdir(parents=True, exist_ok=True)

    vis_dir = OUTPUT_DIR / "visualizations"
    vis_dir.mkdir(parents=True, exist_ok=True)

    # Write dataset.yaml
    yaml_content = f"""# YOLOv8-pose card detection dataset
# Auto-generated by generate_yolo_dataset.py

path: {OUTPUT_DIR.resolve().as_posix()}
train: images/train
val: images/val

# Classes
names:
  0: card

# Keypoints: 4 corners (TL, TR, BR, BL), each with (x, y, visibility)
kpt_shape: [4, 3]
flip_idx: [1, 0, 3, 2]
"""
    (OUTPUT_DIR / "dataset.yaml").write_text(yaml_content)
    print(f"Wrote {OUTPUT_DIR / 'dataset.yaml'}")

    vis_count = 0

    for split, count in [("train", num_train), ("val", num_val)]:
        print(f"\nGenerating {count} {split} samples...")
        success = 0
        attempts = 0
        max_attempts = count * 3  # Allow some failures

        while success < count and attempts < max_attempts:
            attempts += 1

            # Pick random card
            card_path = str(random.choice(card_files))

            result = generate_sample(card_path)
            if result is None:
                continue

            canvas, corners = result

            # Validate: corners should form a reasonable quad
            area = cv2.contourArea(corners.astype(np.int32))
            if area < 500:  # Too small
                continue

            # Save image
            img_name = f"{split}_{success:05d}.jpg"
            img_path = OUTPUT_DIR / "images" / split / img_name
            cv2.imwrite(
                str(img_path),
                cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR),
                [cv2.IMWRITE_JPEG_QUALITY, 90],
            )

            # Save label
            label_name = f"{split}_{success:05d}.txt"
            label_path = OUTPUT_DIR / "labels" / split / label_name
            label_str = corners_to_yolo_pose(corners, CANVAS_SIZE)
            label_path.write_text(label_str)

            # Visualization for first N
            if vis_count < visualize_n:
                vis_path = str(vis_dir / f"vis_{split}_{success:03d}.jpg")
                visualize_sample(canvas, corners, vis_path)
                vis_count += 1

            success += 1
            if success % 500 == 0:
                print(f"  {split}: {success}/{count}")

        print(f"  {split}: {success}/{count} generated ({attempts} attempts)")

    # Summary
    n_train = len(list((OUTPUT_DIR / "images" / "train").glob("*.jpg")))
    n_val = len(list((OUTPUT_DIR / "images" / "val").glob("*.jpg")))
    print(f"\nDataset ready:")
    print(f"  Train: {n_train} images")
    print(f"  Val:   {n_val} images")
    print(f"  Output: {OUTPUT_DIR.resolve()}")
    print(f"  Visualizations: {vis_dir.resolve()}")
    print(f"  YAML: {OUTPUT_DIR / 'dataset.yaml'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate YOLO-pose card detection dataset")
    parser.add_argument("--num-train", type=int, default=5000, help="Number of training samples")
    parser.add_argument("--num-val", type=int, default=500, help="Number of validation samples")
    parser.add_argument("--visualize", type=int, default=10, help="Number of samples to visualize")
    args = parser.parse_args()

    generate_dataset(
        num_train=args.num_train,
        num_val=args.num_val,
        visualize_n=args.visualize,
    )
