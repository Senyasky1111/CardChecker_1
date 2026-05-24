"""
Benchmark 4 card detectors: YOLO-pose, OpenCV, DocTR, PaddleOCR.

For each detector: detect card → warp → CLIP embedding → compare to ground truth.

Usage:
    python scripts/benchmark_detectors.py                # 100 SSP cards
    python scripts/benchmark_detectors.py --cards 50     # fewer cards
    python scripts/benchmark_detectors.py --real-only     # only real photos
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.card_detector import CARD_W, CARD_H, CARD_ASPECT, DetectionResult, order_corners, warp_card

# ── Detector wrappers ──────────────────────────────────────────────

class YOLODetector:
    """Our custom YOLO-pose detector."""
    name = "YOLO-pose"

    def __init__(self):
        from src.yolo_card_detector import YOLOCardDetector
        self.det = YOLOCardDetector()

    def detect(self, img: Image.Image) -> DetectionResult:
        return self.det.detect(img)


class OpenCVDetector:
    """Our custom OpenCV contour detector."""
    name = "OpenCV"

    def __init__(self):
        from src.card_detector import CardDetector
        self.det = CardDetector()

    def detect(self, img: Image.Image) -> DetectionResult:
        return self.det.detect(img)


class DocTRDetector:
    """DocTR pretrained document detector (DBNet)."""
    name = "DocTR"

    def __init__(self):
        os.environ["USE_TORCH"] = "1"
        from doctr.models import detection_predictor
        self.model = detection_predictor(arch="db_resnet50", pretrained=True)

    def detect(self, img: Image.Image) -> DetectionResult:
        img_np = np.array(img.convert("RGB"))

        # DocTR expects [0, 1] float RGB
        doc_input = img_np[:, :, :3].astype(np.float32) / 255.0

        # Run detection
        result = self.model([doc_input])

        # result is [{"words": [array([x1,y1,x2,y2,conf]), ...]}]
        page = result[0]
        words = page.get("words", [])
        if len(words) < 3:
            return self._fallback(img)

        h, w = img_np.shape[:2]

        # Collect all text box corners (normalized coords)
        all_points = []
        for word in words:
            x1, y1, x2, y2 = word[:4]
            all_points.extend([
                [x1 * w, y1 * h],
                [x2 * w, y1 * h],
                [x2 * w, y2 * h],
                [x1 * w, y2 * h],
            ])

        all_points = np.array(all_points, dtype=np.float32)
        hull = cv2.convexHull(all_points)
        hull = hull.reshape(-1, 2)

        # Fit minimum area rectangle → 4 corners
        rect = cv2.minAreaRect(hull)
        box = cv2.boxPoints(rect)
        corners = order_corners(box)

        # Expand slightly (text is inside card border)
        center = corners.mean(axis=0)
        corners = center + (corners - center) * 1.05
        corners = np.clip(corners, [0, 0], [w - 1, h - 1]).astype(np.float32)

        warped = warp_card(img_np, corners)
        avg_conf = float(np.mean([w[4] for w in words]))
        return DetectionResult(
            corners=corners,
            confidence=avg_conf,
            method="doctr",
            card_found=True,
            warped=warped,
        )

    def _fallback(self, img: Image.Image) -> DetectionResult:
        """No detection — resize to card dimensions."""
        warped = img.resize((CARD_W, CARD_H), Image.LANCZOS)
        h, w = np.array(img).shape[:2]
        corners = np.array([[0,0],[w,0],[w,h],[0,h]], dtype=np.float32)
        return DetectionResult(corners=corners, confidence=0.0,
                               method="doctr_fallback", card_found=False, warped=warped)


class PaddleOCRDetector:
    """PaddleOCR pretrained text/document detector."""
    name = "PaddleOCR"

    def __init__(self):
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        from paddleocr import PaddleOCR
        self.ocr = PaddleOCR(use_textline_orientation=True, lang="en")

    def detect(self, img: Image.Image) -> DetectionResult:
        img_np = np.array(img)
        h, w = img_np.shape[:2]

        # PaddleOCR returns text boxes — we use them to find the card boundary
        result = self.ocr.ocr(img_np, cls=True)

        if not result or not result[0]:
            return self._fallback(img)

        # Collect all text box corners
        all_points = []
        for line in result[0]:
            box = line[0]  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            for pt in box:
                all_points.append(pt)

        if len(all_points) < 4:
            return self._fallback(img)

        all_points = np.array(all_points, dtype=np.float32)

        # Convex hull of all text regions → card boundary
        hull = cv2.convexHull(all_points)
        hull = hull.reshape(-1, 2)

        # Fit minimum area rectangle
        rect = cv2.minAreaRect(hull)
        box = cv2.boxPoints(rect)
        corners = order_corners(box)

        # Add small margin (text is inside card, border is outside)
        center = corners.mean(axis=0)
        margin = 1.03  # 3% expansion
        corners = center + (corners - center) * margin
        corners = np.clip(corners, [0, 0], [w - 1, h - 1]).astype(np.float32)

        warped = warp_card(img_np, corners)
        return DetectionResult(
            corners=corners,
            confidence=0.9,
            method="paddleocr",
            card_found=True,
            warped=warped,
        )

    def _fallback(self, img: Image.Image) -> DetectionResult:
        warped = img.resize((CARD_W, CARD_H), Image.LANCZOS)
        h, w = np.array(img).shape[:2]
        corners = np.array([[0,0],[w,0],[w,h],[0,h]], dtype=np.float32)
        return DetectionResult(corners=corners, confidence=0.0,
                               method="paddle_fallback", card_found=False, warped=warped)


class PassthroughDetector:
    """Baseline: no detection, just resize. For pre-cropped images."""
    name = "Passthrough"

    def detect(self, img: Image.Image) -> DetectionResult:
        warped = img.resize((CARD_W, CARD_H), Image.LANCZOS)
        w, h = img.size
        corners = np.array([[0,0],[w,0],[w,h],[0,h]], dtype=np.float32)
        return DetectionResult(corners=corners, confidence=1.0,
                               method="passthrough", card_found=True, warped=warped)


# ── CLIP similarity scorer ─────────────────────────────────────────

class CLIPScorer:
    """Score warped images using CLIP similarity to database reference."""

    def __init__(self):
        from transformers import CLIPProcessor, CLIPModel
        import pickle, faiss

        index_dir = Path("models/card_index")
        meta = pickle.load(open(index_dir / "metadata.pkl", "rb"))
        model_name = meta.get("model_name", "openai/clip-vit-large-patch14")

        print(f"Loading CLIP model: {model_name}")
        self.model = CLIPModel.from_pretrained(model_name)
        self.processor = CLIPProcessor.from_pretrained(model_name, use_fast=False)
        self.model.eval()

        # Try both possible names
        faiss_path = index_dir / "cards.faiss"
        if not faiss_path.exists():
            faiss_path = index_dir / "card_vectors.faiss"
        self.index = faiss.read_index(str(faiss_path))
        self.cards_by_idx = meta["cards_by_idx"]
        print(f"CLIP ready: {self.index.ntotal} cards indexed")

    def identify(self, warped: Image.Image, top_k: int = 5) -> list[dict]:
        """Return top-k card matches with similarity scores."""
        import torch

        inputs = self.processor(images=warped, return_tensors="pt")
        with torch.no_grad():
            vision_out = self.model.vision_model(pixel_values=inputs["pixel_values"])
            embedding = self.model.visual_projection(vision_out.pooler_output)
        # Normalize
        norm = torch.norm(embedding, dim=-1, keepdim=True)
        embedding = embedding / norm.clamp(min=1e-8)
        vec = embedding.cpu().numpy().astype(np.float32)

        scores, indices = self.index.search(vec, top_k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            card = self.cards_by_idx.get(int(idx), {})
            results.append({
                "tcgdex_id": card.get("_tcgdex_id", "?"),
                "name": card.get("_name", "?"),
                "score": float(score),
            })
        return results


# ── Main benchmark ──────────────────────────────────────────────────

def load_test_images(cards_json: Path, images_dir: Path) -> list[tuple[dict, Path]]:
    """Load test cards with local image paths."""
    with open(cards_json) as f:
        cards = json.load(f)

    pairs = []
    for card in cards:
        tid = card["tcgdex_id"]
        sid = tid.rsplit("-", 1)[0] if "-" in tid else ""
        img_path = images_dir / sid / f"en_{tid}.jpg"
        if img_path.exists():
            pairs.append((card, img_path))
    return pairs


def run_benchmark(detectors, test_pairs, scorer, save_dir: Path):
    """Run all detectors on all test images, score with CLIP."""
    save_dir.mkdir(parents=True, exist_ok=True)
    results = {d.name: [] for d in detectors}

    for i, (card, img_path) in enumerate(test_pairs):
        img = Image.open(img_path).convert("RGB")
        expected_tid = card["tcgdex_id"]
        expected_name = card.get("eng_name") or card.get("name", "")

        for det in detectors:
            t0 = time.time()
            try:
                det_result = det.detect(img)
                latency_ms = (time.time() - t0) * 1000

                if det_result.warped is None:
                    results[det.name].append({
                        "tid": expected_tid, "correct": False,
                        "method": det_result.method, "latency_ms": latency_ms,
                    })
                    continue

                # CLIP identify
                t1 = time.time()
                matches = scorer.identify(det_result.warped, top_k=5)
                clip_ms = (time.time() - t1) * 1000

                top = matches[0] if matches else {}
                correct = top.get("tcgdex_id") == expected_tid

                results[det.name].append({
                    "tid": expected_tid,
                    "expected": expected_name,
                    "got": top.get("name", "?"),
                    "got_tid": top.get("tcgdex_id", "?"),
                    "correct": correct,
                    "score": top.get("score", 0),
                    "method": det_result.method,
                    "det_ms": round(latency_ms, 1),
                    "clip_ms": round(clip_ms, 1),
                    "card_found": det_result.card_found,
                })

            except Exception as e:
                results[det.name].append({
                    "tid": expected_tid, "correct": False,
                    "method": "ERROR", "error": str(e)[:100],
                })

        if (i + 1) % 25 == 0:
            print(f"\n  [{i+1}/{len(test_pairs)}]")
            for det in detectors:
                ok = sum(1 for r in results[det.name] if r.get("correct"))
                print(f"    {det.name:15s}: {ok}/{len(results[det.name])}")

    return results


def print_results(results: dict):
    """Print comparison table."""
    sep = "=" * 70
    print(f"\n{sep}")
    print("DETECTOR BENCHMARK RESULTS")
    print(sep)

    for name, rows in results.items():
        n = len(rows)
        if n == 0:
            continue
        ok = sum(1 for r in rows if r.get("correct"))
        found = sum(1 for r in rows if r.get("card_found", False))
        avg_det = sum(r.get("det_ms", 0) for r in rows) / n
        avg_clip = sum(r.get("clip_ms", 0) for r in rows) / n
        avg_score = sum(r.get("score", 0) for r in rows) / n
        errors = sum(1 for r in rows if r.get("method") == "ERROR")

        print(f"\n  {name}:")
        print(f"    Accuracy:    {ok}/{n} ({100*ok/n:.0f}%)")
        print(f"    Detected:    {found}/{n}")
        print(f"    Avg CLIP:    {avg_score:.4f}")
        print(f"    Detection:   {avg_det:.0f}ms")
        print(f"    CLIP:        {avg_clip:.0f}ms")
        print(f"    Total:       {avg_det + avg_clip:.0f}ms")
        if errors:
            print(f"    Errors:      {errors}")

    # Show disagreements
    names = list(results.keys())
    if len(names) >= 2:
        print(f"\n{'─'*70}")
        print("Disagreements (first 10):")
        base = results[names[0]]
        for i, row in enumerate(base):
            votes = {n: results[n][i].get("correct", False) for n in names if i < len(results[n])}
            if len(set(votes.values())) > 1:
                expected = row.get("expected", "?")[:25]
                line = f"  {expected:25s} "
                for n in names:
                    v = "OK" if votes.get(n) else "MISS"
                    got = results[n][i].get("got", "?")[:15] if not votes.get(n) else ""
                    line += f" {n[:6]}={v}"
                    if got:
                        line += f"({got})"
                print(line)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cards", type=int, default=100)
    parser.add_argument("--real-only", action="store_true")
    args = parser.parse_args()

    images_dir = Path("data/cardmarket/images")
    cards_json = Path("data/test_100_cards.json")

    if not cards_json.exists():
        print(f"Missing {cards_json}. Run the test card selector first.")
        return

    print("Loading test images...")
    test_pairs = load_test_images(cards_json, images_dir)
    if args.cards < len(test_pairs):
        test_pairs = test_pairs[:args.cards]
    print(f"Loaded {len(test_pairs)} test images")

    # Add real photos if available
    real_photos = [
        Path("test_image.jpg"),
        Path("test_piplup.jpg"),
        Path("photo_2026-02-01_18-04-37.jpg"),
        Path("photo_2026-02-15_20-41-37.jpg"),
        Path("photo_2026-03-07_23-20-11.jpg"),
    ]
    real_count = 0
    for rp in real_photos:
        if rp.exists():
            test_pairs.append(({"tcgdex_id": f"real_{rp.stem}", "name": rp.stem}, rp))
            real_count += 1
    if real_count:
        print(f"Added {real_count} real photos")

    # Initialize detectors
    print("\nInitializing detectors...")
    detectors = []

    print("  Loading Passthrough (baseline)...")
    detectors.append(PassthroughDetector())

    print("  Loading YOLO-pose...")
    try:
        detectors.append(YOLODetector())
    except Exception as e:
        print(f"    YOLO failed: {e}")

    print("  Loading OpenCV...")
    try:
        detectors.append(OpenCVDetector())
    except Exception as e:
        print(f"    OpenCV failed: {e}")

    print("  Loading DocTR...")
    try:
        detectors.append(DocTRDetector())
    except Exception as e:
        print(f"    DocTR failed: {e}")

    print("  Loading PaddleOCR...")
    try:
        detectors.append(PaddleOCRDetector())
    except Exception as e:
        print(f"    PaddleOCR failed: {e}")

    print(f"\n{len(detectors)} detectors ready")

    # Initialize CLIP scorer
    print("\nInitializing CLIP scorer...")
    scorer = CLIPScorer()

    # Run benchmark
    print(f"\nRunning benchmark: {len(detectors)} detectors x {len(test_pairs)} images...")
    results = run_benchmark(detectors, test_pairs, scorer, Path("data/benchmark"))

    # Print results
    print_results(results)

    # Save full results
    out_path = Path("data/benchmark/results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nFull results saved to {out_path}")


if __name__ == "__main__":
    main()
