"""
Batch test collector number OCR detection across card images.

Tests a sample of images from different sets, comparing detected numbers
against the expected number encoded in the filename (e.g. en_sv08-057.jpg → 57).

Usage:
    py -3.11 scripts/test_number_detection.py
    py -3.11 scripts/test_number_detection.py --sets sv01 sv08 swsh1 --per-set 20
    py -3.11 scripts/test_number_detection.py --all --per-set 5
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image
from src.ocr import CardOCR

IMAGES_DIR = Path("./data/cardmarket/images")

# Extract expected number from tcgdex_id in filename
# e.g. "en_sv08-057.jpg" → set="sv08", number=57
# e.g. "en_A1-001.jpg" → set="A1", number=1
FILENAME_RE = re.compile(r"^[a-z]{2}(?:-[a-z]{2})?_(.+?)[-_](\d+)\.jpg$")


def parse_expected(filename: str) -> tuple[str | None, int | None]:
    """Extract expected (set_id, number) from image filename."""
    m = FILENAME_RE.match(filename)
    if not m:
        return None, None
    set_part = m.group(1)
    num_str = m.group(2)
    try:
        return set_part, int(num_str)
    except ValueError:
        return set_part, None


def collect_test_images(
    sets: list[str] | None, per_set: int, all_sets: bool
) -> list[tuple[Path, str, int]]:
    """Collect (image_path, set_id, expected_number) tuples."""
    images = []

    if sets:
        target_dirs = [IMAGES_DIR / s for s in sets]
    elif all_sets:
        target_dirs = sorted(d for d in IMAGES_DIR.iterdir() if d.is_dir())
    else:
        # Default: representative sets from different eras
        default_sets = [
            "sv01", "sv06", "sv08",  # Scarlet & Violet
            "swsh1", "swsh5",        # Sword & Shield
            "sm1", "sm11",           # Sun & Moon
            "xy1",                   # XY
            "bw1",                   # Black & White
            "A1", "A2",              # Pocket
        ]
        target_dirs = [IMAGES_DIR / s for s in default_sets if (IMAGES_DIR / s).exists()]

    for set_dir in target_dirs:
        if not set_dir.is_dir():
            continue

        count = 0
        for img_path in sorted(set_dir.glob("en_*.jpg")):
            if img_path.stat().st_size == 0:
                continue

            set_id, expected_num = parse_expected(img_path.name)
            if expected_num is None:
                continue

            images.append((img_path, set_id, expected_num))
            count += 1
            if count >= per_set:
                break

    return images


def run_test(images: list[tuple[Path, str, int]], verbose: bool = True):
    """Run OCR on all images and report accuracy."""
    ocr = CardOCR()

    total = 0
    correct = 0
    detected = 0
    wrong = 0
    missed = 0

    set_stats: dict[str, dict] = {}
    failures: list[dict] = []

    t0 = time.time()

    for img_path, set_id, expected_num in images:
        total += 1

        image = Image.open(img_path).convert("RGB")

        # Since these are clean dataset images (not photos), skip card detection
        card_img = image.resize((600, 825), Image.LANCZOS)

        collector_number, confidence = ocr._extract_collector_number(card_img)

        # Track per-set stats
        if set_id not in set_stats:
            set_stats[set_id] = {"total": 0, "correct": 0, "detected": 0, "wrong": 0, "missed": 0}
        set_stats[set_id]["total"] += 1

        if collector_number is not None:
            detected += 1
            set_stats[set_id]["detected"] += 1

            if collector_number.number == expected_num:
                correct += 1
                set_stats[set_id]["correct"] += 1
            else:
                wrong += 1
                set_stats[set_id]["wrong"] += 1
                failures.append({
                    "file": img_path.name,
                    "set": set_id,
                    "expected": expected_num,
                    "got": collector_number.number,
                    "total_got": collector_number.total,
                    "raw": collector_number.raw,
                    "confidence": confidence,
                })
                if verbose:
                    print(f"  WRONG: {img_path.name}  expected={expected_num}  got={collector_number.number}/{collector_number.total}  raw=\"{collector_number.raw}\"")
        else:
            missed += 1
            set_stats[set_id]["missed"] += 1
            failures.append({
                "file": img_path.name,
                "set": set_id,
                "expected": expected_num,
                "got": None,
                "raw": "",
                "confidence": 0,
            })
            if verbose:
                print(f"  MISS:  {img_path.name}  expected={expected_num}  (no number detected)")

    elapsed = time.time() - t0

    # Print summary
    print("\n" + "=" * 60)
    print("COLLECTOR NUMBER DETECTION TEST RESULTS")
    print("=" * 60)
    print(f"Total images tested: {total}")
    print(f"Numbers detected:    {detected} ({detected/total*100:.1f}%)" if total else "")
    print(f"Correct:             {correct} ({correct/total*100:.1f}%)" if total else "")
    print(f"Wrong number:        {wrong}")
    print(f"Not detected:        {missed}")
    print(f"Time: {elapsed:.1f}s ({elapsed/total*1000:.0f}ms per card)" if total else "")

    # Per-set breakdown
    print(f"\n{'Set':<12} {'Total':>6} {'OK':>6} {'Wrong':>6} {'Miss':>6} {'Accuracy':>10}")
    print("-" * 52)
    for sid in sorted(set_stats.keys()):
        s = set_stats[sid]
        acc = s["correct"] / s["total"] * 100 if s["total"] else 0
        print(f"{sid:<12} {s['total']:>6} {s['correct']:>6} {s['wrong']:>6} {s['missed']:>6} {acc:>9.1f}%")

    # Show failures
    if failures:
        print(f"\n--- Failures ({len(failures)}) ---")
        for f in failures[:30]:
            if f["got"] is not None:
                print(f"  {f['file']}: expected {f['expected']}, got {f['got']} (raw: \"{f['raw']}\")")
            else:
                print(f"  {f['file']}: expected {f['expected']}, NOT DETECTED")
        if len(failures) > 30:
            print(f"  ... and {len(failures) - 30} more")

    return {
        "total": total, "correct": correct, "detected": detected,
        "wrong": wrong, "missed": missed, "elapsed": elapsed,
        "set_stats": set_stats, "failures": failures,
    }


def main():
    parser = argparse.ArgumentParser(description="Test collector number OCR detection")
    parser.add_argument("--sets", nargs="+", help="Specific sets to test (e.g. sv01 sv08)")
    parser.add_argument("--per-set", type=int, default=10, help="Images per set (default: 10)")
    parser.add_argument("--all", action="store_true", help="Test all available sets")
    parser.add_argument("--verbose", action="store_true", default=True)
    parser.add_argument("--quiet", action="store_true", help="Only show summary")
    args = parser.parse_args()

    if args.quiet:
        args.verbose = False

    print("Collecting test images...")
    images = collect_test_images(args.sets, args.per_set, args.all)
    print(f"Found {len(images)} images to test\n")

    if not images:
        print("No images found! Check --sets or image directory.")
        return

    run_test(images, verbose=args.verbose)


if __name__ == "__main__":
    main()
