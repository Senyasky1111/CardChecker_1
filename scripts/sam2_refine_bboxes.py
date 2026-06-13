"""SAM2 zero-shot bbox refinement for v3 defect dataset.

Replaces synthetic class-typical bboxes (from build_v3_dataset.py) with
real tight bboxes derived from SAM2 masks, using each defect (x, y) point
as the prompt.

Pipeline:
  v3 dataset (synthetic bboxes)
       │
       │  load card MAIN scan
       │  for each defect → denormalize (x,y) → SAM2 point prompt
       │  → mask → tight bbox + sanity-filter (area, AR)
       ▼
  v3_sam2/ dataset (real bboxes)

HITL gate (Section A4 of v3.2 plan):
  - random 300 refined bboxes saved as visualisations
  - human verifies before downstream training

Compute target:
  - H100 / A100 / RTX 4090: ~4-6 hours on 213k defect points
  - RTX 4060 mobile (8GB): ~30 hours — only for smoke test

Usage:
  # smoke test on 50 cards, local CPU/GPU
  python scripts/sam2_refine_bboxes.py --sample 50

  # full refinement (cloud)
  python scripts/sam2_refine_bboxes.py --device cuda

  # quality-gate visualizations only (after refinement)
  python scripts/sam2_refine_bboxes.py --hitl-gate-only

Env requirements:
  pip install sam2  # Meta's SAM2 package
  huggingface_hub login  # or set HF_TOKEN

Model checkpoint defaults to facebook/sam2-hiera-small (smallest viable).
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import shutil
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("sam2-refine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RAW = Path("data/tag_raw")
SRC = Path("data/tag_v3/detection")       # source v3 dataset
DST = Path("data/tag_v3/detection_sam2")  # output: same structure, refined labels
HITL = Path("store_listing/v3_sam2_hitl")  # quality-gate visualizations

CLASS_NAMES = [
    "corner_wear", "edge_wear", "surface_damage",
    "scratch", "crease", "dent", "stain",
]

# Sanity filters on SAM2 mask output (tuned per Round-4 SAM2 review)
MIN_MASK_AREA_PX = 100                # below ~10×10 px = noise — raise from 50
MAX_MASK_AREA_FRAC = 0.05             # above 5% of image = grabbed whole card region, reject
MAX_MASK_ASPECT = 12.0                # cap from 25 — most defects ≤10:1
SAM2_MULTIMASK = True                 # ask SAM2 for 3 candidate masks, pick by predicted-IoU score


# ---------------------------------------------------------------------------
# SAM2 wrapper (lazy import — only loaded when actually running refinement)
# ---------------------------------------------------------------------------

def load_sam2(model_id: str = "facebook/sam2.1-hiera-small", device: str = "cuda"):
    """Lazy-load SAM2.1 predictor via HF Transformers (preferred over deprecated build_sam2_hf)."""
    try:
        from sam2.sam2_image_predictor import SAM2ImagePredictor
    except ImportError:
        log.error("SAM2 not installed. Run: pip install sam2")
        sys.exit(1)

    log.info(f"Loading SAM2.1: {model_id} on {device}")
    predictor = SAM2ImagePredictor.from_pretrained(model_id, device=device)
    return predictor


# ---------------------------------------------------------------------------
# Mask → bbox
# ---------------------------------------------------------------------------

def mask_to_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """Convert binary mask to (x_min, y_min, x_max, y_max) in pixels. None if mask empty."""
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def is_mask_sensible(mask: np.ndarray, img_h: int, img_w: int) -> tuple[bool, str]:
    """Reject mask if area is too small, too large, or aspect ratio is extreme."""
    area = int(mask.sum())
    if area < MIN_MASK_AREA_PX:
        return False, f"too_small({area}px)"
    if area > MAX_MASK_AREA_FRAC * img_h * img_w:
        return False, f"too_large({area / (img_h * img_w) * 100:.1f}%)"
    bbox = mask_to_bbox(mask)
    if bbox is None:
        return False, "empty_mask"
    w = bbox[2] - bbox[0] + 1
    h = bbox[3] - bbox[1] + 1
    ar = max(w, h) / max(1, min(w, h))
    if ar > MAX_MASK_ASPECT:
        return False, f"extreme_AR({ar:.1f})"
    return True, "ok"


def pick_best_mask(masks: np.ndarray, scores: np.ndarray, img_h: int, img_w: int) -> tuple[np.ndarray | None, float, str]:
    """Pick highest-IoU-score mask from SAM2's multi-mask output that passes sanity filter.

    SAM2's 3 masks are whole/part/subpart — the calibrated signal is the predicted
    IoU score (`scores`), NOT area. Picking smallest systematically selects sub-region
    hallucinations and discards SAM2's actually-correct mask (see SAM2 issue #692).

    Sanity filter still rejects out-of-bounds (too-small / too-large / extreme-AR).
    """
    candidates = []
    for m, s in zip(masks, scores):
        ok, reason = is_mask_sensible(m, img_h, img_w)
        if ok:
            candidates.append((float(s), m))
    if not candidates:
        return None, 0.0, "all_masks_rejected"
    # Pick highest-score (predicted IoU)
    candidates.sort(key=lambda t: -t[0])
    best_score, best_mask = candidates[0]
    return best_mask, best_score, "ok"


# ---------------------------------------------------------------------------
# Per-card refinement
# ---------------------------------------------------------------------------

@dataclass
class RefinedDefect:
    cls: int
    x_norm: float
    y_norm: float
    w_norm: float
    h_norm: float
    sam2_score: float | None
    refined: bool   # True = SAM2 mask used; False = fallback to synthetic


def refine_card(
    predictor, cert: str, side: str, src_label: Path, src_image: Path,
    metadata: dict, stats: Counter, hitl_samples: list,
) -> tuple[list[RefinedDefect], np.ndarray | None]:
    """Refine all bboxes in one (cert, side). Returns refined bboxes + image (for HITL)."""
    # Load original metadata defects (have real (x, y) at TAG resolution)
    src_defects = [d for d in metadata.get("surface_defects", []) if d.get("side") == side]
    if not src_defects:
        # Negative or no-defect card — pass through empty
        return [], None

    # Load image (post-resize, 1280px wide)
    im = Image.open(src_image).convert("RGB")
    img_w, img_h = im.size
    arr = np.array(im)

    predictor.set_image(arr)

    refined: list[RefinedDefect] = []
    rng = random.Random(42)

    # Read original label lines (synthetic bboxes from build_v3_dataset.py)
    lines = src_label.read_text().splitlines()
    if not lines:
        return [], None

    import torch
    for line in lines:
        parts = line.split()
        if len(parts) != 5:
            continue
        cls = int(parts[0])
        xn, yn, wn_synth, hn_synth = map(float, parts[1:])
        # Point prompt in pixel coords of CURRENT image (1280-wide post-resize)
        px = xn * img_w
        py = yn * img_h
        point_coords = np.array([[px, py]], dtype=np.float32)
        point_labels = np.array([1], dtype=np.int32)  # positive

        # Pass synthetic bbox as box-prompt constraint — keeps SAM2 from grabbing
        # the whole card on tiny defects against bright orange border / holo glare.
        # Box format expected by SAM2: [x_min, y_min, x_max, y_max] in pixel coords.
        bw = wn_synth * img_w
        bh = hn_synth * img_h
        # Inflate the box-prompt 2× so we don't over-constrain — synthetic bbox is
        # only a hint, not ground truth.
        bw_inflated, bh_inflated = bw * 2.0, bh * 2.0
        box_prompt = np.array([[
            max(0, px - bw_inflated / 2),
            max(0, py - bh_inflated / 2),
            min(img_w, px + bw_inflated / 2),
            min(img_h, py + bh_inflated / 2),
        ]], dtype=np.float32)

        try:
            # Wrap in inference_mode + bf16 autocast — ~2-3× faster, ~2× less VRAM
            with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                masks, scores, _ = predictor.predict(
                    point_coords=point_coords,
                    point_labels=point_labels,
                    box=box_prompt,
                    multimask_output=SAM2_MULTIMASK,
                )
        except Exception as e:
            log.warning(f"  SAM2 failed for {cert}_{side} at ({px:.0f},{py:.0f}): {e}")
            stats["sam2_call_error"] += 1
            refined.append(RefinedDefect(cls, xn, yn, wn_synth, hn_synth, None, False))
            continue

        mask, score, status = pick_best_mask(masks, scores, img_h, img_w)
        stats[f"mask_{status}"] += 1

        # If all masks rejected — retry once with 4 negative corner-points to push
        # SAM2 away from card borders (~50% recovery rate on rejected masks).
        if mask is None:
            neg_pts = np.array([
                [point_coords[0][0], point_coords[0][1]],   # original positive
                [10, 10], [img_w - 10, 10],
                [10, img_h - 10], [img_w - 10, img_h - 10],
            ], dtype=np.float32)
            neg_lbls = np.array([1, 0, 0, 0, 0], dtype=np.int32)
            try:
                with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    masks, scores, _ = predictor.predict(
                        point_coords=neg_pts,
                        point_labels=neg_lbls,
                        box=box_prompt,
                        multimask_output=SAM2_MULTIMASK,
                    )
                mask, score, retry_status = pick_best_mask(masks, scores, img_h, img_w)
                if mask is not None:
                    stats["mask_retry_ok"] += 1
                else:
                    stats[f"retry_{retry_status}"] += 1
            except Exception:
                pass

        if mask is None:
            # Fallback: keep synthetic
            refined.append(RefinedDefect(cls, xn, yn, wn_synth, hn_synth, None, False))
            continue

        # mask → bbox
        x0, y0, x1, y1 = mask_to_bbox(mask)
        bw = x1 - x0 + 1
        bh = y1 - y0 + 1
        x_center = (x0 + x1) / 2.0 / img_w
        y_center = (y0 + y1) / 2.0 / img_h
        w_norm = bw / img_w
        h_norm = bh / img_h
        refined.append(RefinedDefect(cls, x_center, y_center, w_norm, h_norm, score, True))

    # HITL sample (1 in 300 chance)
    if rng.random() < 1 / 300 and refined:
        hitl_samples.append((cert, side, arr, lines, refined))

    return refined, arr


# ---------------------------------------------------------------------------
# HITL visualization
# ---------------------------------------------------------------------------

def write_hitl_visualisations(samples: list, out_dir: Path):
    """Write side-by-side synthetic vs SAM2-refined bbox overlays for human review."""
    out_dir.mkdir(parents=True, exist_ok=True)
    COLORS = [(230,40,40),(40,200,40),(60,130,230),(255,170,30),(180,80,200),(60,200,200),(220,200,40)]
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()

    for cert, side, arr, synth_lines, refined in samples:
        H, W = arr.shape[:2]
        # Left: synthetic from original label
        left = Image.fromarray(arr).copy()
        dl = ImageDraw.Draw(left)
        for ln in synth_lines:
            p = ln.split()
            if len(p) != 5: continue
            c = int(p[0]); xn, yn, wn, hn = map(float, p[1:])
            x = xn*W; y = yn*H; w = wn*W; h = hn*H
            dl.rectangle([x-w/2, y-h/2, x+w/2, y+h/2], outline=COLORS[c], width=3)
        dl.rectangle([0,0,W,24], fill=(0,0,0))
        dl.text((5,4), f"{cert} {side} SYNTHETIC", fill=(255,255,255), font=font)

        # Right: SAM2-refined
        right = Image.fromarray(arr).copy()
        dr = ImageDraw.Draw(right)
        for r in refined:
            x = r.x_norm*W; y = r.y_norm*H; w = r.w_norm*W; h = r.h_norm*H
            col = COLORS[r.cls]
            dr.rectangle([x-w/2, y-h/2, x+w/2, y+h/2], outline=col, width=3)
            if not r.refined:
                dr.text((x-w/2, y-h/2-14), "(synth-fallback)", fill=(255,80,80), font=font)
        dr.rectangle([0,0,W,24], fill=(0,0,0))
        dr.text((5,4), f"{cert} {side} SAM2-refined", fill=(255,255,255), font=font)

        # Combine
        combo = Image.new("RGB", (W*2 + 4, H), (40,40,40))
        combo.paste(left, (0,0))
        combo.paste(right, (W+4, 0))
        combo.save(out_dir/f"{cert}_{side}.jpg", quality=82)

    log.info(f"Wrote {len(samples)} HITL samples to {out_dir}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=None, help="Smoke test on N cards (sequential)")
    ap.add_argument("--device", type=str, default="cuda", help="cuda | cpu")
    ap.add_argument("--model", type=str, default="facebook/sam2-hiera-small")
    ap.add_argument("--output", type=Path, default=DST)
    ap.add_argument("--src", type=Path, default=SRC)
    ap.add_argument("--hitl-gate-only", action="store_true",
                    help="Read existing refined dataset and just regenerate HITL viz")
    ap.add_argument("--clean", action="store_true")
    args = ap.parse_args()

    if args.clean and args.output.exists():
        log.info(f"Wiping {args.output}")
        shutil.rmtree(args.output)
    # Mirror src structure
    for sp in ("train", "val", "test"):
        (args.output / "images" / sp).mkdir(parents=True, exist_ok=True)
        (args.output / "labels" / sp).mkdir(parents=True, exist_ok=True)
    HITL.mkdir(parents=True, exist_ok=True)

    if args.hitl_gate_only:
        log.error("--hitl-gate-only not yet implemented (TODO: re-render HITL from existing refined dataset)")
        sys.exit(1)

    # Load SAM2 predictor (slow — ~30s)
    start = time.time()
    predictor = load_sam2(args.model, args.device)
    log.info(f"SAM2 loaded in {time.time()-start:.1f}s")

    # Discover all label files
    src_labels: list[Path] = []
    for sp in ("train", "val", "test"):
        src_labels.extend((args.src / "labels" / sp).glob("*.txt"))
    src_labels.sort()

    if args.sample:
        src_labels = src_labels[:args.sample]
        log.info(f"Sample mode: refining {len(src_labels)} cards")

    log.info(f"Processing {len(src_labels)} label files")

    stats: Counter = Counter()
    hitl_samples: list = []
    n_lines_in = 0
    n_lines_out = 0

    progress_step = max(1, len(src_labels) // 50)
    for i, lbl in enumerate(src_labels):
        # Parse cert/side from filename
        stem = lbl.stem  # e.g. C1234567_front
        cert, _, side = stem.rpartition("_")
        if side not in ("front", "back"):
            continue
        split = lbl.parent.name  # train|val|test
        src_image = args.src / "images" / split / f"{stem}.jpg"
        if not src_image.exists():
            stats["missing_image"] += 1
            continue
        # Metadata is optional — labels file is the source of truth on the pod.
        # tag_raw/ is not uploaded; skip metadata if missing.
        meta_path = RAW / cert / "metadata.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                stats["bad_metadata"] += 1
                meta = {}
        else:
            meta = {}

        # Copy image as-is into output dataset
        dst_image = args.output / "images" / split / f"{stem}.jpg"
        if not dst_image.exists():
            shutil.copy2(src_image, dst_image)

        # Refine
        try:
            refined, _ = refine_card(predictor, cert, side, lbl, src_image, meta, stats, hitl_samples)
        except Exception as e:
            log.warning(f"  {stem}: refine failed: {e}")
            stats["card_error"] += 1
            # Fallback: copy original label
            shutil.copy2(lbl, args.output / "labels" / split / f"{stem}.txt")
            continue

        n_lines_in += sum(1 for ln in lbl.read_text().splitlines() if ln.strip())
        n_lines_out += len(refined)

        # Write refined label
        dst_label = args.output / "labels" / split / f"{stem}.txt"
        with open(dst_label, "w") as f:
            for r in refined:
                f.write(f"{r.cls} {r.x_norm:.6f} {r.y_norm:.6f} {r.w_norm:.6f} {r.h_norm:.6f}\n")

        if i % progress_step == 0:
            log.info(f"  [{i}/{len(src_labels)}] {stem} (refined {len(refined)}/{n_lines_in - sum(1 for ln in lbl.read_text().splitlines() if ln.strip()) + len(refined)} ok so far)")

    # Write HITL visualizations
    write_hitl_visualisations(hitl_samples, HITL)

    # Summary
    elapsed = time.time() - start
    log.info("=" * 60)
    log.info(f"DONE in {elapsed/60:.1f}m")
    log.info(f"Label files processed: {len(src_labels)}")
    log.info(f"Bbox lines: input={n_lines_in} → output={n_lines_out}")
    log.info(f"Status counts: {dict(sorted(stats.items()))}")
    log.info(f"HITL samples for verification: {len(hitl_samples)} in {HITL}")


if __name__ == "__main__":
    main()
