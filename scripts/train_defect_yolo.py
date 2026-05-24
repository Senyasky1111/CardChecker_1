#!/usr/bin/env python3
"""Train YOLO defect detector on TAG dataset.

Usage:
    # Validate dataset before training
    python scripts/train_defect_yolo.py --validate

    # Train locally (requires GPU)
    python scripts/train_defect_yolo.py --train

    # Train with custom params
    python scripts/train_defect_yolo.py --train --imgsz 1280 --epochs 200 --batch 4

    # Export to ONNX
    python scripts/train_defect_yolo.py --export --model runs/detect/train/weights/best.pt

    # Visualize predictions on test set
    python scripts/train_defect_yolo.py --visualize --model runs/detect/train/weights/best.pt
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = ROOT / "data" / "tag_dataset"
DATASET_YAML = DATASET_DIR / "dataset.yaml"
OUTPUT_DIR = ROOT / "models" / "yolo_defect"


def validate_dataset():
    """Check dataset integrity: images exist, labels parse, report stats."""
    if not DATASET_YAML.exists():
        print(f"ERROR: {DATASET_YAML} not found. Run: python scripts/scrape_tag.py --convert-only")
        return False

    print(f"Dataset: {DATASET_YAML}")
    with open(DATASET_YAML) as f:
        print(f.read())

    total_images = 0
    total_annotations = 0
    class_counts = Counter()
    empty_labels = 0
    missing_images = 0
    bad_labels = 0

    for split in ["train", "val", "test"]:
        img_dir = DATASET_DIR / "images" / split
        lbl_dir = DATASET_DIR / "labels" / split

        if not img_dir.exists():
            print(f"WARNING: {img_dir} not found")
            continue

        images = list(img_dir.glob("*.jpg"))
        labels = list(lbl_dir.glob("*.txt"))

        split_annotations = 0
        split_empty = 0

        for img_path in images:
            label_path = lbl_dir / (img_path.stem + ".txt")
            if not label_path.exists():
                missing_images += 1
                continue

            content = label_path.read_text().strip()
            if not content:
                split_empty += 1
                empty_labels += 1
                continue

            for line in content.split("\n"):
                parts = line.strip().split()
                if len(parts) != 5:
                    bad_labels += 1
                    continue
                try:
                    cls_id = int(parts[0])
                    x, y, w, h = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
                    if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
                        bad_labels += 1
                        continue
                    class_counts[cls_id] += 1
                    split_annotations += 1
                except (ValueError, IndexError):
                    bad_labels += 1

        total_images += len(images)
        total_annotations += split_annotations

        print(f"\n{split:>5s}: {len(images):5d} images, {split_annotations:5d} annotations, {split_empty:3d} empty (negatives)")

    print(f"\n{'TOTAL':>5s}: {total_images:5d} images, {total_annotations:5d} annotations, {empty_labels:3d} negatives")

    if bad_labels:
        print(f"\nWARNING: {bad_labels} malformed label lines")
    if missing_images:
        print(f"WARNING: {missing_images} images without label files")

    # Load class names from yaml
    import yaml
    with open(DATASET_YAML) as f:
        cfg = yaml.safe_load(f)
    names = cfg.get("names", {})
    if isinstance(names, str):
        names = json.loads(names)
    # Convert string keys to int
    names = {int(k): v for k, v in names.items()}

    print("\nClass distribution:")
    for cls_id in sorted(class_counts):
        name = names.get(cls_id, f"class_{cls_id}")
        count = class_counts[cls_id]
        bar = "#" * min(50, count // 10)
        print(f"  {cls_id}: {name:20s} {count:5d} {bar}")

    # Check class balance
    if class_counts:
        max_count = max(class_counts.values())
        min_count = min(class_counts.values())
        ratio = max_count / max(min_count, 1)
        print(f"\nClass imbalance ratio: {ratio:.1f}x (max/min)")
        if ratio > 50:
            print("WARNING: Severe class imbalance. Consider merging rare classes or oversampling.")

    ok = total_annotations > 0 and bad_labels == 0
    print(f"\nValidation: {'PASSED' if ok else 'ISSUES FOUND'}")
    return ok


def train(args):
    """Train YOLOv11 defect detector."""
    try:
        from ultralytics import YOLO
    except ImportError:
        print("ERROR: ultralytics not installed. Run: pip install ultralytics")
        sys.exit(1)

    if not DATASET_YAML.exists():
        print(f"ERROR: {DATASET_YAML} not found. Run: python scripts/scrape_tag.py --convert-only")
        sys.exit(1)

    # Use YOLOv11m pretrained on COCO
    model = YOLO(args.model_base)

    print(f"\nTraining config:")
    print(f"  Dataset:  {DATASET_YAML}")
    print(f"  Model:    {args.model_base}")
    print(f"  Image sz: {args.imgsz}")
    print(f"  Epochs:   {args.epochs}")
    print(f"  Batch:    {args.batch}")
    print(f"  Patience: {args.patience}")
    print(f"  Output:   {OUTPUT_DIR}")

    results = model.train(
        data=str(DATASET_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        patience=args.patience,
        lr0=0.001,
        lrf=0.01,
        # Augmentation tuned for card images
        mosaic=1.0,
        flipud=0.5,
        fliplr=0.5,
        degrees=5.0,       # slight rotation (cards are rectified)
        scale=0.3,          # mild scaling
        hsv_h=0.015,        # color jitter (different cameras)
        hsv_s=0.3,
        hsv_v=0.3,
        translate=0.1,
        # Don't use heavy geometric transforms
        perspective=0.0,
        shear=0.0,
        # Training params
        close_mosaic=15,     # disable mosaic in last 15 epochs
        warmup_epochs=5,
        cos_lr=True,
        # Output
        project=str(OUTPUT_DIR),
        name="train",
        exist_ok=True,
        save=True,
        plots=True,
        verbose=True,
    )

    print(f"\nTraining complete!")
    print(f"Best model: {OUTPUT_DIR / 'train' / 'weights' / 'best.pt'}")
    return results


def export_onnx(args):
    """Export trained model to ONNX format."""
    try:
        from ultralytics import YOLO
    except ImportError:
        print("ERROR: ultralytics not installed.")
        sys.exit(1)

    model_path = args.model
    if not Path(model_path).exists():
        # Try default location
        model_path = str(OUTPUT_DIR / "train" / "weights" / "best.pt")

    if not Path(model_path).exists():
        print(f"ERROR: Model not found at {model_path}")
        sys.exit(1)

    print(f"Exporting {model_path} to ONNX...")
    model = YOLO(model_path)
    model.export(format="onnx", imgsz=args.imgsz, simplify=True)

    onnx_path = Path(model_path).with_suffix(".onnx")
    # Copy to models dir
    dest = OUTPUT_DIR / "defect_detector.onnx"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(onnx_path, dest)
    print(f"ONNX model saved to: {dest}")


def visualize(args):
    """Run predictions on test set and save visual results."""
    try:
        from ultralytics import YOLO
    except ImportError:
        print("ERROR: ultralytics not installed.")
        sys.exit(1)

    model_path = args.model
    if not Path(model_path).exists():
        model_path = str(OUTPUT_DIR / "train" / "weights" / "best.pt")

    if not Path(model_path).exists():
        print(f"ERROR: Model not found at {model_path}")
        sys.exit(1)

    test_images = DATASET_DIR / "images" / "test"
    if not test_images.exists():
        print("ERROR: Test images not found")
        sys.exit(1)

    model = YOLO(model_path)
    results = model.predict(
        source=str(test_images),
        save=True,
        project=str(OUTPUT_DIR),
        name="visualize",
        exist_ok=True,
        conf=0.25,
        line_width=2,
    )

    print(f"\nVisualized {len(results)} images → {OUTPUT_DIR / 'visualize'}")


def main():
    parser = argparse.ArgumentParser(description="Train YOLO defect detector")
    parser.add_argument("--validate", action="store_true", help="Validate dataset")
    parser.add_argument("--train", action="store_true", help="Train model")
    parser.add_argument("--export", action="store_true", help="Export to ONNX")
    parser.add_argument("--visualize", action="store_true", help="Visualize predictions")

    parser.add_argument("--model-base", default="yolo11m.pt", help="Base model for training")
    parser.add_argument("--model", default="", help="Trained model path for export/visualize")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size")
    parser.add_argument("--epochs", type=int, default=150, help="Training epochs")
    parser.add_argument("--batch", type=int, default=8, help="Batch size")
    parser.add_argument("--patience", type=int, default=30, help="Early stopping patience")

    args = parser.parse_args()

    if not any([args.validate, args.train, args.export, args.visualize]):
        args.validate = True

    if args.validate:
        validate_dataset()

    if args.train:
        train(args)

    if args.export:
        export_onnx(args)

    if args.visualize:
        visualize(args)


if __name__ == "__main__":
    main()
