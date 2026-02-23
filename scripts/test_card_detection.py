"""
Test card detection on real card images with synthetic transformations.

Takes card images from the dataset, applies realistic distortions
(rotation, perspective, background), then runs detection and shows results.

Usage:
    py -3.11 scripts/test_card_detection.py
    py -3.11 scripts/test_card_detection.py --image path/to/image.jpg
    py -3.11 scripts/test_card_detection.py --save-dir output/
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

# Add src/ to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from card_detector import CardDetector, CARD_W, CARD_H


# ── Synthetic scene generation ───────────────────────────────────────

def create_synthetic_scene(
    card_img: Image.Image,
    rotation_deg: float = 0,
    scale: float = 0.5,
    perspective_strength: float = 0.0,
    bg_color: tuple = (40, 40, 60),
    canvas_size: tuple = (1200, 900),
) -> tuple[Image.Image, np.ndarray]:
    """
    Place a card image onto a synthetic background with transformations.

    Returns (scene_image, ground_truth_corners).
    """
    card = np.array(card_img.convert("RGB"))
    ch, cw = card.shape[:2]

    # Scale card
    new_w = int(cw * scale)
    new_h = int(ch * scale)
    card = cv2.resize(card, (new_w, new_h), interpolation=cv2.INTER_AREA)

    # Source corners (card image)
    src_pts = np.array([
        [0, 0],
        [new_w, 0],
        [new_w, new_h],
        [0, new_h],
    ], dtype=np.float32)

    # Apply rotation
    cx, cy = canvas_size[0] / 2, canvas_size[1] / 2
    angle_rad = np.radians(rotation_deg)

    # Compute destination corners (centered + rotated)
    dst_pts = []
    for sx, sy in src_pts:
        # Center the card
        x = sx - new_w / 2
        y = sy - new_h / 2
        # Rotate
        rx = x * np.cos(angle_rad) - y * np.sin(angle_rad)
        ry = x * np.sin(angle_rad) + y * np.cos(angle_rad)
        # Translate to canvas center
        dst_pts.append([rx + cx, ry + cy])

    dst_pts = np.array(dst_pts, dtype=np.float32)

    # Apply perspective distortion
    if perspective_strength > 0:
        # Simulate viewing angle — shift top or bottom edge
        shift = int(new_w * perspective_strength * 0.3)
        # Trapezoid: narrow the top
        dst_pts[0][0] += shift * 0.5
        dst_pts[1][0] -= shift * 0.5
        dst_pts[0][1] += shift * 0.3
        dst_pts[1][1] += shift * 0.3

    # Warp card onto canvas
    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    canvas = np.full((canvas_size[1], canvas_size[0], 3), bg_color, dtype=np.uint8)

    # Add some noise to background
    noise = np.random.randint(0, 20, canvas.shape, dtype=np.uint8)
    canvas = cv2.add(canvas, noise)

    cv2.warpPerspective(card, M, (canvas_size[0], canvas_size[1]),
                        dst=canvas, borderMode=cv2.BORDER_TRANSPARENT)

    return Image.fromarray(canvas), dst_pts


def save_result_grid(
    original: Image.Image,
    scene: Image.Image,
    annotated: Image.Image,
    warped: Image.Image,
    output_path: Path,
):
    """Save a 2x2 grid: original | scene | annotated | warped."""
    cell_w, cell_h = 600, 450
    grid = Image.new("RGB", (cell_w * 2, cell_h * 2), (30, 30, 30))

    # Resize keeping aspect ratio
    def fit(img, w, h):
        img = img.copy()
        img.thumbnail((w - 10, h - 10), Image.LANCZOS)
        return img

    imgs = [
        ("Original", fit(original, cell_w, cell_h)),
        ("Scene", fit(scene, cell_w, cell_h)),
        ("Detected", fit(annotated, cell_w, cell_h)),
        ("Warped", fit(warped, cell_w, cell_h)),
    ]

    for idx, (label, img) in enumerate(imgs):
        x = (idx % 2) * cell_w + (cell_w - img.width) // 2
        y = (idx // 2) * cell_h + (cell_h - img.height) // 2
        grid.paste(img, (x, y))

        # Add label
        grid_np = np.array(grid)
        lx = (idx % 2) * cell_w + 10
        ly = (idx // 2) * cell_h + 25
        cv2.putText(grid_np, label, (lx, ly),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)
        grid = Image.fromarray(grid_np)

    grid.save(output_path)
    return grid


# ── Main test runner ─────────────────────────────────────────────────

def find_test_images(n: int = 5) -> list[Path]:
    """Find card images from the dataset for testing."""
    images_dir = Path("./data/cardmarket/images")
    if not images_dir.exists():
        print(f"Images directory not found: {images_dir}")
        return []

    # Collect from subdirectories (set-based layout)
    all_images = []
    for p in images_dir.rglob("*.jpg"):
        all_images.append(p)
    for p in images_dir.rglob("*.webp"):
        all_images.append(p)

    if not all_images:
        print("No images found!")
        return []

    # Pick evenly spaced
    step = max(len(all_images) // n, 1)
    selected = [all_images[i * step] for i in range(min(n, len(all_images)))]
    return selected


def run_test(
    image_path: Path,
    detector: CardDetector,
    save_dir: Path | None = None,
) -> dict:
    """Run detection test on a single image."""
    original = Image.open(image_path).convert("RGB")
    name = image_path.stem

    print(f"\n{'='*60}")
    print(f"Testing: {image_path.name} ({original.size[0]}x{original.size[1]})")

    results = []

    # Test 1: Card image as-is (no transformation — should be trivial)
    t0 = time.time()
    result = detector.detect(original)
    dt = (time.time() - t0) * 1000
    print(f"  Direct: method={result.method}, conf={result.confidence:.3f}, "
          f"found={result.card_found}, {dt:.0f}ms")
    results.append(("direct", result, original, dt))

    # Test 2-5: Synthetic scenes with various distortions
    test_configs = [
        {"rotation_deg": 0, "scale": 0.6, "perspective_strength": 0.0,
         "label": "centered"},
        {"rotation_deg": 15, "scale": 0.5, "perspective_strength": 0.0,
         "label": "rotated_15deg"},
        {"rotation_deg": -10, "scale": 0.45, "perspective_strength": 0.3,
         "label": "perspective"},
        {"rotation_deg": 25, "scale": 0.4, "perspective_strength": 0.5,
         "label": "hard_perspective"},
    ]

    for cfg in test_configs:
        label = cfg.pop("label")
        scene, gt_corners = create_synthetic_scene(original, **cfg)

        t0 = time.time()
        result = detector.detect(scene)
        dt = (time.time() - t0) * 1000

        print(f"  {label}: method={result.method}, conf={result.confidence:.3f}, "
              f"found={result.card_found}, {dt:.0f}ms")
        results.append((label, result, scene, dt))

    # Save grid for the "perspective" test case
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
        for label, result, scene, dt in results:
            annotated = detector.visualize(scene, result)
            warped = result.warped or Image.new("RGB", (CARD_W, CARD_H), (60, 60, 60))
            grid_path = save_dir / f"{name}_{label}.jpg"
            save_result_grid(original, scene, annotated, warped, grid_path)

    return {
        "image": image_path.name,
        "tests": [
            {"label": l, "method": r.method, "confidence": r.confidence,
             "found": r.card_found, "time_ms": dt}
            for l, r, _, dt in results
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Test card detection")
    parser.add_argument("--image", type=str, help="Single image to test")
    parser.add_argument("--save-dir", type=str, default="output/detection_test",
                        help="Directory to save result images")
    parser.add_argument("--n", type=int, default=5,
                        help="Number of images to test from dataset")
    args = parser.parse_args()

    detector = CardDetector()
    save_dir = Path(args.save_dir) if args.save_dir else None

    if args.image:
        path = Path(args.image)
        if not path.exists():
            print(f"Image not found: {path}")
            return
        run_test(path, detector, save_dir)
    else:
        images = find_test_images(args.n)
        if not images:
            print("No test images found. Put card images in data/cardmarket/images/")
            return

        all_results = []
        for img_path in images:
            result = run_test(img_path, detector, save_dir)
            all_results.append(result)

        # Summary
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        total = 0
        found = 0
        for r in all_results:
            for t in r["tests"]:
                total += 1
                if t["found"]:
                    found += 1

        print(f"Detection rate: {found}/{total} ({found/total*100:.1f}%)")

        if save_dir:
            print(f"\nResult images saved to: {save_dir}")


if __name__ == "__main__":
    main()
