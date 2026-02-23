"""
Train YOLOv8n-pose model for card corner detection.

This script is designed to run either:
  1. Locally (if you have a GPU)
  2. In Google Colab (upload dataset zip, run this script)

The model learns to detect a card bounding box + 4 corner keypoints
(TL, TR, BR, BL) in a single forward pass.

Usage (local):
    py -3.11 scripts/train_yolo_card.py

Usage (Colab):
    1. Upload yolo_card_dataset.zip to Colab
    2. !unzip yolo_card_dataset.zip -d /content/dataset
    3. !pip install ultralytics
    4. !python train_yolo_card.py --data /content/dataset/dataset.yaml --device 0

After training, download best.pt from runs/pose/train/weights/best.pt
and place it in models/yolo_card/best.pt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Train YOLOv8n-pose for card detection")
    parser.add_argument(
        "--data",
        type=str,
        default="data/yolo_card_dataset/dataset.yaml",
        help="Path to dataset.yaml",
    )
    parser.add_argument("--epochs", type=int, default=100, help="Training epochs")
    parser.add_argument("--batch", type=int, default=16, help="Batch size")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size")
    parser.add_argument("--device", type=str, default="", help="Device: '' (auto), '0' (GPU), 'cpu'")
    parser.add_argument("--patience", type=int, default=20, help="Early stopping patience")
    parser.add_argument("--workers", type=int, default=4, help="Dataloader workers")
    parser.add_argument("--project", type=str, default="runs/pose", help="Project directory")
    parser.add_argument("--name", type=str, default="card_detector", help="Run name")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    args = parser.parse_args()

    # Check dataset exists
    data_path = Path(args.data)
    if not data_path.exists():
        print(f"ERROR: Dataset YAML not found: {data_path}")
        print("Run 'py -3.11 scripts/generate_yolo_dataset.py' first to generate the dataset.")
        sys.exit(1)

    try:
        from ultralytics import YOLO
    except ImportError:
        print("ERROR: ultralytics not installed.")
        print("Install with: pip install ultralytics")
        sys.exit(1)

    # Load pretrained YOLOv8n-pose
    # This is the smallest pose model (~3.2M params), good for CPU inference
    print("Loading YOLOv8n-pose base model...")
    model = YOLO("yolov8n-pose.pt")

    print(f"\nTraining config:")
    print(f"  Dataset: {data_path.resolve()}")
    print(f"  Epochs:  {args.epochs}")
    print(f"  Batch:   {args.batch}")
    print(f"  ImgSz:   {args.imgsz}")
    print(f"  Device:  {args.device or 'auto'}")
    print(f"  Output:  {args.project}/{args.name}")
    print()

    # Train
    results = model.train(
        data=str(data_path.resolve()),
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        device=args.device if args.device else None,
        patience=args.patience,
        workers=args.workers,
        project=args.project,
        name=args.name,
        resume=args.resume,
        # Pose-specific settings
        pose=12.0,           # Pose loss gain (default)
        kobj=1.0,            # Keypoint obj loss gain
        # Augmentation (dataset already has augmentation, keep YOLO augments light)
        hsv_h=0.01,          # Hue augmentation
        hsv_s=0.3,           # Saturation augmentation
        hsv_v=0.3,           # Value augmentation
        degrees=10.0,        # Rotation (our dataset already has rotation)
        translate=0.1,       # Translation
        scale=0.3,           # Scale augmentation
        perspective=0.0005,  # Perspective (light, dataset already has it)
        flipud=0.0,          # No vertical flip for cards
        fliplr=0.5,          # Horizontal flip (flip_idx handles corner swap)
        mosaic=0.5,          # Mosaic augmentation (half the time)
        mixup=0.0,           # No mixup
        # Output
        save=True,
        save_period=10,      # Save checkpoint every 10 epochs
        plots=True,
        verbose=True,
    )

    # Print results
    print("\n" + "=" * 60)
    print("Training complete!")
    print("=" * 60)

    best_path = Path(args.project) / args.name / "weights" / "best.pt"
    if best_path.exists():
        size_mb = best_path.stat().st_size / (1024 * 1024)
        print(f"\nBest model: {best_path} ({size_mb:.1f} MB)")
        print(f"\nTo use the model:")
        print(f"  1. Copy {best_path} to models/yolo_card/best.pt")
        print(f"  2. Or export to ONNX: py -3.11 scripts/export_yolo_onnx.py --model {best_path}")
    else:
        print(f"\nWARNING: best.pt not found at {best_path}")

    return results


if __name__ == "__main__":
    main()
