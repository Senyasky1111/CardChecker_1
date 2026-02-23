"""
End-to-end pipeline test: synthetic scene → detect → warp → OCR → identify.

Creates synthetic photos of cards (rotated, perspective, on backgrounds)
and sends them to /identify-v2 to test the full pipeline.

Usage:
    py -3.11 scripts/test_e2e_pipeline.py

Requires the API server running at localhost:8000.
"""

import io
import json
import random
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import requests
from PIL import Image

API_BASE = "http://localhost:8000"
IMAGES_DIR = Path("data/cardmarket/images")
OUTPUT_DIR = Path("static/e2e_tests")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def create_synthetic_scene(
    card_path: str,
    rotation_deg: float = 0,
    scale: float = 0.5,
    perspective_strength: float = 0.0,
    bg_color: tuple = None,
    canvas_size: tuple = (1200, 900),
) -> Image.Image:
    """
    Place a card image on a canvas with rotation, scaling, and perspective.

    Returns the synthetic scene as a PIL Image.
    """
    card = cv2.imread(str(card_path))
    if card is None:
        raise FileNotFoundError(f"Cannot load: {card_path}")

    card_h, card_w = card.shape[:2]
    cw, ch = canvas_size

    # Scale the card
    new_w = int(card_w * scale)
    new_h = int(card_h * scale)
    card_resized = cv2.resize(card, (new_w, new_h), interpolation=cv2.INTER_AREA)

    # Create canvas with random or specified background
    if bg_color is None:
        bg_color = (
            random.randint(30, 80),
            random.randint(30, 80),
            random.randint(30, 80),
        )
    canvas = np.full((ch, cw, 3), bg_color, dtype=np.uint8)

    # Add some noise to the background
    noise = np.random.randint(0, 20, canvas.shape, dtype=np.uint8)
    canvas = cv2.add(canvas, noise)

    # Source corners of the card (before transform)
    src_pts = np.array([
        [0, 0],
        [new_w, 0],
        [new_w, new_h],
        [0, new_h],
    ], dtype=np.float32)

    # Center position
    cx, cy = cw // 2, ch // 2

    # Apply rotation
    angle_rad = np.radians(rotation_deg)
    cos_a, sin_a = np.cos(angle_rad), np.sin(angle_rad)

    # Rotate around center of card, then translate to canvas center
    rotated_pts = []
    for pt in src_pts:
        x, y = pt[0] - new_w / 2, pt[1] - new_h / 2
        rx = x * cos_a - y * sin_a + cx
        ry = x * sin_a + y * cos_a + cy
        rotated_pts.append([rx, ry])

    dst_pts = np.array(rotated_pts, dtype=np.float32)

    # Apply perspective distortion
    if perspective_strength > 0:
        for i, pt in enumerate(dst_pts):
            dx = random.uniform(-1, 1) * perspective_strength * new_w * 0.1
            dy = random.uniform(-1, 1) * perspective_strength * new_h * 0.1
            dst_pts[i] = [pt[0] + dx, pt[1] + dy]

    # Perspective transform
    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped = cv2.warpPerspective(card_resized, M, (cw, ch))

    # Create mask for blending
    mask = np.zeros((new_h, new_w), dtype=np.uint8)
    mask[:] = 255
    mask_warped = cv2.warpPerspective(mask, M, (cw, ch))

    # Composite card onto canvas
    mask_3ch = cv2.merge([mask_warped, mask_warped, mask_warped])
    canvas = np.where(mask_3ch > 128, warped, canvas)

    return Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))


def send_to_identify(scene: Image.Image, endpoint: str = "/identify-v2") -> dict:
    """Send an image to the API and return the JSON response."""
    buf = io.BytesIO()
    scene.save(buf, format="JPEG", quality=92)
    buf.seek(0)

    resp = requests.post(
        f"{API_BASE}{endpoint}",
        files={"file": ("test_scene.jpg", buf, "image/jpeg")},
        timeout=60,
    )
    return resp.json()


def send_to_detect(scene: Image.Image) -> dict:
    """Send an image to /detect-card and return the JSON response."""
    buf = io.BytesIO()
    scene.save(buf, format="JPEG", quality=92)
    buf.seek(0)

    resp = requests.post(
        f"{API_BASE}/detect-card",
        files={"file": ("test_scene.jpg", buf, "image/jpeg")},
        params={"visualize": "true"},
        timeout=30,
    )
    return resp.json()


def run_test_case(
    card_path: Path,
    label: str,
    rotation: float = 0,
    scale: float = 0.5,
    perspective: float = 0.0,
    bg_color: tuple = None,
) -> dict:
    """Run a single test case and return results."""
    print(f"\n{'='*60}")
    print(f"  Test: {label}")
    print(f"  Card: {card_path.name}")
    print(f"  Params: rot={rotation}deg, scale={scale}, persp={perspective}")
    print(f"{'='*60}")

    # Create scene
    scene = create_synthetic_scene(
        str(card_path),
        rotation_deg=rotation,
        scale=scale,
        perspective_strength=perspective,
        bg_color=bg_color,
    )

    # Save scene
    scene_name = f"{card_path.stem}_{label.replace(' ', '_')}"
    scene_path = OUTPUT_DIR / f"{scene_name}_scene.jpg"
    scene.save(str(scene_path), quality=92)

    # 1) Test detection only
    t0 = time.time()
    detect_result = send_to_detect(scene)
    detect_ms = (time.time() - t0) * 1000

    print(f"\n  [detect-card] {detect_ms:.0f}ms")
    print(f"    card_found: {detect_result.get('card_found')}")
    print(f"    method: {detect_result.get('method')}")
    print(f"    confidence: {detect_result.get('confidence', 0):.3f}")

    # 2) Test full pipeline (identify-v2)
    t0 = time.time()
    identify_result = send_to_identify(scene)
    identify_ms = (time.time() - t0) * 1000

    print(f"\n  [identify-v2] {identify_ms:.0f}ms (server-side: {identify_result.get('processing_time_ms', 0):.0f}ms)")
    print(f"    success: {identify_result.get('success')}")
    print(f"    method: {identify_result.get('method')}")
    print(f"    ocr_name: {identify_result.get('ocr_name')}")
    print(f"    ocr_number: {identify_result.get('ocr_number')}")
    print(f"    confidence: {identify_result.get('confidence', 0):.3f}")

    top = identify_result.get("top_match")
    if top:
        print(f"    => {top.get('name', '?')} ({top.get('set_name', '?')})")
        print(f"      tcgdex_id: {top.get('tcgdex_id', '?')}")
        print(f"      collector#: {top.get('collector_number', '?')}")
        if top.get("price_trend"):
            print(f"      price: EUR {top['price_trend']:.2f} (trend)")
    else:
        print(f"    => NO MATCH")

    alts = identify_result.get("alternatives", [])
    if alts:
        print(f"    alternatives: {len(alts)}")
        for alt in alts[:3]:
            print(f"      - {alt.get('name', '?')} ({alt.get('set_name', '?')})")

    return {
        "card": card_path.name,
        "label": label,
        "detect": detect_result,
        "identify": identify_result,
        "scene_path": str(scene_path),
    }


def main():
    # Check server is running
    try:
        health = requests.get(f"{API_BASE}/health", timeout=5).json()
        print(f"Server OK: {health['cards_in_db']} cards in DB, {health['cards_indexed']} indexed")
    except Exception as e:
        print(f"ERROR: Server not reachable at {API_BASE}: {e}")
        sys.exit(1)

    # Pick test cards — diverse set of English cards
    test_cards = []

    # Find cards from different sets
    sets_to_try = ["A1", "A1a", "A2", "A2a", "A2b", "sv8", "sv8pt5", "sv09"]
    for set_dir in sets_to_try:
        set_path = IMAGES_DIR / set_dir
        if not set_path.exists():
            continue
        en_cards = sorted(set_path.glob("en_*.jpg"))
        if en_cards:
            # Pick a card with a clear name (not first/last which might be energy/secret)
            idx = min(10, len(en_cards) - 1)
            test_cards.append(en_cards[idx])
            if len(test_cards) >= 5:
                break

    # Also try a Japanese card
    for set_dir in sets_to_try:
        set_path = IMAGES_DIR / set_dir
        if not set_path.exists():
            continue
        ja_cards = sorted(set_path.glob("ja_*.jpg"))
        if ja_cards:
            test_cards.append(ja_cards[min(10, len(ja_cards) - 1)])
            break

    if not test_cards:
        print("ERROR: No test cards found in data/cardmarket/images/")
        sys.exit(1)

    print(f"\nUsing {len(test_cards)} test cards:")
    for c in test_cards:
        print(f"  - {c}")

    # Test scenarios
    results = []

    for card_path in test_cards:
        # Test 1: Direct card (no transformation — as if the image IS the card)
        r = run_test_case(card_path, "direct", rotation=0, scale=0.95, perspective=0)
        results.append(r)

        # Test 2: Slight rotation (15 degrees)
        r = run_test_case(card_path, "rot15", rotation=15, scale=0.5, perspective=0)
        results.append(r)

        # Test 3: Perspective + rotation (simulating card held at angle)
        r = run_test_case(card_path, "persp", rotation=8, scale=0.45, perspective=0.5)
        results.append(r)

    # Summary
    print(f"\n\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")

    total = len(results)
    detected = sum(1 for r in results if r["detect"].get("card_found"))
    identified = sum(1 for r in results if r["identify"].get("success"))

    print(f"\n  Total tests:    {total}")
    print(f"  Cards detected: {detected}/{total} ({100*detected/total:.0f}%)")
    print(f"  Cards identified: {identified}/{total} ({100*identified/total:.0f}%)")

    print(f"\n  Per-test details:")
    for r in results:
        det = "OK" if r["detect"].get("card_found") else "FAIL"
        ident = "OK" if r["identify"].get("success") else "FAIL"
        top_name = ""
        top = r["identify"].get("top_match")
        if top:
            top_name = f" => {top.get('name', '?')[:30]}"

        ocr_n = r["identify"].get("ocr_name") or ""
        ocr_num = r["identify"].get("ocr_number") or ""

        print(f"    [{det}|{ident}] {r['card']:30s} {r['label']:8s} "
              f"ocr='{ocr_n[:20]}' #{ocr_num}{top_name}")

    # Save results JSON
    results_path = OUTPUT_DIR / "e2e_results.json"
    # Strip non-serializable data
    for r in results:
        r.pop("scene_path", None)
    with open(str(results_path), "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to: {results_path}")

    return 0 if identified == total else 1


if __name__ == "__main__":
    sys.exit(main())
