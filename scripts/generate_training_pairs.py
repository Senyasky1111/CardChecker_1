"""
Generate synthetic training pairs for CLIP fine-tuning.

Takes clean database card images and applies COMBINED realistic augmentations
that simulate real-world photography conditions:
  - Holographic glare / specular highlights
  - Plastic sleeve reflections
  - Warm/cool/fluorescent lighting
  - Vignetting and shadow
  - Random background surfaces
  - Slight perspective + rotation
  - Brightness/contrast variation
  - Camera noise + JPEG compression

Each augmented image gets 2-5 random augmentations stacked together,
producing realistic combinations (e.g. sleeve + warm light + noise).

Output: data/training_synthetic/
  pairs.jsonl  -- {"augmented_path", "clean_path", "tcgdex_id", "source"}
  {tcgdex_id}/ -- augmented images per card

Usage:
    python scripts/generate_training_pairs.py                     # 5 augmentations per card
    python scripts/generate_training_pairs.py --per-card 10       # 10 per card
    python scripts/generate_training_pairs.py --max-cards 1000    # limit cards
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from tqdm import tqdm

IMAGES_DIR = Path("data/cardmarket/images")
OUTPUT_DIR = Path("data/training_synthetic")
PAIRS_FILE = OUTPUT_DIR / "pairs.jsonl"


# ---------- Individual augmentations ----------

def aug_holographic_glare(img: np.ndarray) -> np.ndarray:
    """Simulate holographic/foil glare with radial gradient."""
    h, w = img.shape[:2]
    result = img.astype(np.float32)

    n_spots = random.randint(1, 4)
    for _ in range(n_spots):
        cx = random.randint(w // 4, 3 * w // 4)
        cy = random.randint(h // 4, 3 * h // 4)
        radius = random.randint(min(h, w) // 6, min(h, w) // 2)

        Y, X = np.ogrid[:h, :w]
        dist = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2).astype(np.float32)
        mask = np.clip(1.0 - dist / radius, 0, 1) ** 2

        color = np.array([random.randint(180, 255) for _ in range(3)], dtype=np.float32)
        glare = mask[:, :, np.newaxis] * color[np.newaxis, np.newaxis, :]
        result += glare * random.uniform(0.15, 0.45)

    return np.clip(result, 0, 255).astype(np.uint8)


def aug_plastic_sleeve(img: np.ndarray) -> np.ndarray:
    """Plastic sleeve: slight blur + reflection band."""
    h, w = img.shape[:2]
    result = cv2.GaussianBlur(img, (3, 3), 0.5) if random.random() > 0.3 else img.copy()
    result = result.astype(np.float32)

    # Add 1-2 reflection bands
    for _ in range(random.randint(1, 2)):
        if random.random() > 0.5:
            y = random.randint(0, h - h // 6)
            band_h = random.randint(h // 10, h // 4)
            y_end = min(y + band_h, h)
            grad = np.linspace(0, 1, y_end - y).reshape(-1, 1, 1)
            grad = np.minimum(grad, grad[::-1]) * 2
            result[y:y_end] += grad * random.uniform(20, 60)
        else:
            x = random.randint(0, w - w // 6)
            band_w = random.randint(w // 10, w // 4)
            x_end = min(x + band_w, w)
            grad = np.linspace(0, 1, x_end - x).reshape(1, -1, 1)
            grad = np.minimum(grad, grad[:, ::-1]) * 2
            result[:, x:x_end] += grad * random.uniform(20, 60)

    return np.clip(result, 0, 255).astype(np.uint8)


def aug_color_shift(img: np.ndarray) -> np.ndarray:
    """Warm/cool/fluorescent lighting shift."""
    img_f = img.astype(np.float32)
    mode = random.choice(["warm", "cool", "fluorescent", "random"])
    if mode == "warm":
        img_f[:, :, 2] *= random.uniform(1.05, 1.20)
        img_f[:, :, 0] *= random.uniform(0.85, 0.95)
    elif mode == "cool":
        img_f[:, :, 0] *= random.uniform(1.05, 1.20)
        img_f[:, :, 2] *= random.uniform(0.85, 0.95)
    elif mode == "fluorescent":
        img_f[:, :, 1] *= random.uniform(1.05, 1.15)
    else:
        for c in range(3):
            img_f[:, :, c] *= random.uniform(0.85, 1.15)
    return np.clip(img_f, 0, 255).astype(np.uint8)


def aug_vignette(img: np.ndarray) -> np.ndarray:
    """Corner darkening."""
    h, w = img.shape[:2]
    Y, X = np.ogrid[:h, :w]
    cx, cy = w // 2, h // 2
    max_dist = np.sqrt(cx ** 2 + cy ** 2)
    dist = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2).astype(np.float32)
    v = 1.0 - (dist / max_dist) * random.uniform(0.2, 0.5)
    return np.clip(img.astype(np.float32) * v[:, :, np.newaxis], 0, 255).astype(np.uint8)


def aug_perspective(img: np.ndarray) -> np.ndarray:
    """Slight perspective warp."""
    h, w = img.shape[:2]
    s = int(min(h, w) * 0.04)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = src + np.random.uniform(-s, s, src.shape).astype(np.float32)
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, M, (w, h), borderValue=(255, 255, 255))


def aug_rotation(img: np.ndarray) -> np.ndarray:
    """Small rotation ±5°."""
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), random.uniform(-5, 5), 1.0)
    return cv2.warpAffine(img, M, (w, h), borderValue=(255, 255, 255))


def aug_brightness_contrast(img: np.ndarray) -> np.ndarray:
    """Random brightness/contrast."""
    alpha = random.uniform(0.7, 1.3)
    beta = random.uniform(-30, 30)
    return np.clip(img.astype(np.float32) * alpha + beta, 0, 255).astype(np.uint8)


def aug_jpeg(img: np.ndarray) -> np.ndarray:
    """JPEG compression artifacts."""
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, random.randint(30, 75)])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def aug_noise(img: np.ndarray) -> np.ndarray:
    """Camera sensor noise."""
    noise = np.random.normal(0, random.uniform(3, 12), img.shape).astype(np.float32)
    return np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def aug_background(img: np.ndarray) -> np.ndarray:
    """Random background padding."""
    h, w = img.shape[:2]
    pad = random.randint(10, 40)
    bg = [random.randint(20, 240) for _ in range(3)]
    canvas = np.full((h + 2 * pad, w + 2 * pad, 3), bg, dtype=np.uint8)
    canvas[pad:pad + h, pad:pad + w] = img
    return cv2.resize(canvas, (w, h), interpolation=cv2.INTER_AREA)


# ---------- Pipeline ----------

AUGMENTATIONS = [
    (aug_holographic_glare, 0.4),
    (aug_plastic_sleeve,    0.3),
    (aug_color_shift,       0.6),
    (aug_vignette,          0.3),
    (aug_perspective,       0.4),
    (aug_rotation,          0.3),
    (aug_brightness_contrast, 0.5),
    (aug_jpeg,              0.4),
    (aug_noise,             0.4),
    (aug_background,        0.2),
]


def augment_image(img: np.ndarray) -> np.ndarray:
    """Apply random combination of 2-5 augmentations."""
    result = img.copy()
    applied = 0

    for fn, prob in AUGMENTATIONS:
        if random.random() < prob:
            try:
                result = fn(result)
                applied += 1
            except Exception:
                pass

    # Ensure at least 2 augmentations
    if applied < 2:
        extras = random.sample(AUGMENTATIONS, 3)
        for fn, _ in extras:
            if applied >= 2:
                break
            try:
                result = fn(result)
                applied += 1
            except Exception:
                pass

    return result


# ---------- Main ----------

def find_all_images() -> list[tuple[Path, str]]:
    """Find all card images → (path, tcgdex_id)."""
    filename_re = re.compile(r"^([a-z]{2}(?:-[a-z]{2})?)_(.+)\.(jpg|png)$")
    pairs = []

    for set_dir in sorted(IMAGES_DIR.iterdir()):
        if not set_dir.is_dir():
            continue
        for img in set_dir.glob("*.jpg"):
            if img.stat().st_size == 0:
                continue
            m = filename_re.match(img.name)
            if m:
                tcgdex_id = m.group(2).replace("_", "-")
                pairs.append((img, tcgdex_id))

    for img in IMAGES_DIR.glob("*.jpg"):
        if img.stat().st_size > 0:
            pairs.append((img, img.stem))

    return pairs


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic training pairs")
    parser.add_argument("--per-card", type=int, default=5, help="Augmentations per card")
    parser.add_argument("--max-cards", type=int, default=0, help="Limit cards (0=all)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Scanning card images...")
    all_images = find_all_images()
    print(f"Found {len(all_images)} card images")

    if args.max_cards > 0:
        random.shuffle(all_images)
        all_images = all_images[:args.max_cards]

    expected = len(all_images) * args.per_card
    print(f"Generating {args.per_card} augmentations each = ~{expected} pairs")

    total = 0
    errors = 0

    with open(PAIRS_FILE, "w", encoding="utf-8") as f:
        for img_path, tcgdex_id in tqdm(all_images, desc="Augmenting"):
            try:
                img = cv2.imread(str(img_path))
                if img is None:
                    errors += 1
                    continue
            except Exception:
                errors += 1
                continue

            card_dir = OUTPUT_DIR / tcgdex_id.replace("/", "_")
            card_dir.mkdir(parents=True, exist_ok=True)

            for i in range(args.per_card):
                out_path = card_dir / f"aug_{i:03d}.jpg"
                try:
                    aug = augment_image(img)
                    cv2.imwrite(str(out_path), aug, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    f.write(json.dumps({
                        "augmented_path": str(out_path),
                        "clean_path": str(img_path),
                        "tcgdex_id": tcgdex_id,
                        "source": "synthetic",
                    }, ensure_ascii=False) + "\n")
                    total += 1
                except Exception:
                    errors += 1

    print(f"\nDone! {total} augmented images generated")
    print(f"Errors: {errors}")
    print(f"Pairs: {PAIRS_FILE}")
    print(f"Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
