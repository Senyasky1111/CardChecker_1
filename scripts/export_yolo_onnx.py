"""
Export trained YOLOv8-pose card detector to ONNX format.

ONNX format allows inference with onnxruntime (fast CPU inference)
without requiring the heavy ultralytics package in production.

Usage:
    py -3.11 scripts/export_yolo_onnx.py
    py -3.11 scripts/export_yolo_onnx.py --model runs/pose/card_detector/weights/best.pt

Output: models/yolo_card/card_detector.onnx
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Export YOLOv8-pose to ONNX")
    parser.add_argument(
        "--model",
        type=str,
        default="runs/pose/card_detector/weights/best.pt",
        help="Path to trained .pt model",
    )
    parser.add_argument("--imgsz", type=int, default=640, help="Image size")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="models/yolo_card",
        help="Output directory for ONNX file",
    )
    parser.add_argument("--simplify", action="store_true", default=True, help="Simplify ONNX graph")
    parser.add_argument("--dynamic", action="store_true", default=False, help="Dynamic batch size")
    args = parser.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        print(f"ERROR: Model not found: {model_path}")
        print("Train a model first with: py -3.11 scripts/train_yolo_card.py")
        sys.exit(1)

    try:
        from ultralytics import YOLO
    except ImportError:
        print("ERROR: ultralytics not installed.")
        print("Install with: pip install ultralytics")
        sys.exit(1)

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading model from {model_path}...")
    model = YOLO(str(model_path))

    print(f"Exporting to ONNX (imgsz={args.imgsz}, simplify={args.simplify})...")
    export_path = model.export(
        format="onnx",
        imgsz=args.imgsz,
        simplify=args.simplify,
        dynamic=args.dynamic,
    )

    # Move to output directory
    export_path = Path(export_path)
    dest = output_dir / "card_detector.onnx"

    if export_path != dest:
        shutil.copy2(str(export_path), str(dest))
        print(f"Copied to {dest}")

    # Also copy the .pt model for reference
    pt_dest = output_dir / "best.pt"
    if not pt_dest.exists() or pt_dest.resolve() != model_path.resolve():
        shutil.copy2(str(model_path), str(pt_dest))
        print(f"Copied .pt to {pt_dest}")

    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"\nExport complete!")
    print(f"  ONNX model: {dest} ({size_mb:.1f} MB)")
    print(f"  Image size: {args.imgsz}x{args.imgsz}")
    print(f"\nTo use in production:")
    print(f"  - pip install onnxruntime")
    print(f"  - The server will auto-detect the ONNX model at {dest}")

    # Quick validation
    try:
        import onnxruntime as ort
        sess = ort.InferenceSession(str(dest))
        inp = sess.get_inputs()[0]
        out = sess.get_outputs()[0]
        print(f"\nONNX validation OK:")
        print(f"  Input:  {inp.name} {inp.shape} {inp.type}")
        print(f"  Output: {out.name} {out.shape} {out.type}")
    except ImportError:
        print("\nNote: Install onnxruntime to validate: pip install onnxruntime")
    except Exception as e:
        print(f"\nWARNING: ONNX validation failed: {e}")


if __name__ == "__main__":
    main()
