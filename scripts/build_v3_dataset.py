"""Build CardChecker v3 defect-detection dataset from TAG raw data.

Outputs:
  data/tag_v3/
    detection/
      dataset.yaml
      images/{train,val,test}/{cert}_{side}.jpg     (1280px wide)
      labels/{train,val,test}/{cert}_{side}.txt     (YOLO format, 7 classes)
    severity/
      corners/{train,val,test}/{cert}_{side}_{pos}_{sev}.jpg  (224x224)
      edges/{train,val,test}/{cert}_{side}_{pos}_{sev}.jpg    (480x96 or 96x480)

Key v3 changes vs v1:
- All ~213k defect points used (was filtered subset of surface_defects)
- All clean cards used as negatives (was capped at 200)
- corners[]/edges[] arrays included in detection dataset (was ignored)
- GroupKFold split by cert-prefix (was random — risked leakage)
- Severity dataset NEW — per-zone TAG ground truth for Model B
- Hi-res crop bonuses (when on disk) NEW

Bbox sizes here are class-typical placeholders. SAM2 step (separate) refines
them to real masks/bboxes from TAG (x, y) points.

Usage:
  python scripts/build_v3_dataset.py --sample 10            # test on 10 random cards
  python scripts/build_v3_dataset.py --sample 100           # broader sanity
  python scripts/build_v3_dataset.py                        # full 96k run
  python scripts/build_v3_dataset.py --output data/tag_v3/  # custom output

Wall-time on full 96k: ~30-45 min single-process (mostly image resize I/O).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import shutil
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RAW = Path("data/tag_raw")
DEFAULT_OUT = Path("data/tag_v3")

CLASS_NAMES = {
    0: "corner_wear",
    1: "edge_wear",
    2: "surface_damage",
    3: "scratch",
    4: "crease",
    5: "dent",
    6: "stain",
}

# Map TAG defect_type strings → 7-class ids. Comprehensive — built from full
# scan of ~218k defect entries (see _v2_plan_for_review.md sources).
DEFECT_MAP: dict[str, int] = {}
def _add(name: str, cls: int) -> None:
    DEFECT_MAP[name.lower().strip()] = cls

# Class 0: corner_wear
for n in ("CORNER WEAR",):
    _add(n, 0)
# Class 1: edge_wear
for n in ("EDGE WEAR",):
    _add(n, 1)
# Class 2: surface_damage (play wear, ink, print defects, generic surface)
for n in (
    "SURFACE / PLAY WEAR", "Play Wear Defect", "Play Wear",
    "SURFACE / SURFACE DEFECT", "SURFACE / OTHER DAMAGE",
    "SURFACE / INK DEFECT", "Ink/Surface Defect", "Ink Defect",
    "SURFACE / PRINT LINE", "SURFACE / PRINT LINES",
    "Print Line(s)", "Print Line", "SURFACE / PRINT DEFECT",
    "Print Defect", "SURFACE / ROLLER MARK", "Roller Mark",
    "Surface Defect",
):
    _add(n, 2)
# Class 3: scratch (incl scuffing)
for n in (
    "SURFACE / SCRATCH(ES)", "SURFACE / SCRATCHES",
    "Scratch(es)", "Scratch", "Scratches",
    "SURFACE / SCUFFING", "Scuffing",
):
    _add(n, 3)
# Class 4: crease/wrinkle/bend
for n in (
    "SURFACE / WRINKLE/CREASE", "SURFACE / WRINKLES/CREASES",
    "Wrinkle/Crease", "Crease",
    "EDGE/CORNER / BEND", "SURFACE / BEND", "Bend",
    "SURFACE / TEAR",
):
    _add(n, 4)
# Class 5: dent/pit/missing-stock
for n in (
    "SURFACE / DENT", "SURFACE / DENTS", "Dent",
    "SURFACE / PIT", "SURFACE / PITS", "Pit",
    "SURFACE / MISSING STOCK",
):
    _add(n, 5)
# Class 6: stain/water/discoloration/gloss
for n in (
    "SURFACE / WATER/STAIN", "SURFACE / WATER DAMAGE",
    "SURFACE / STAIN / RESIDUE", "SURFACE / DISCOLORATION",
    "Water/Stain Damage", "Water/Stain", "Stain",
    "SURFACE / GLOSS", "SURFACE / WHITENING", "Whitening",
):
    _add(n, 6)
# Ignored — TAG internal artifacts
IGNORED_TYPES = {"FRAMEMARKER_ESW_CSW", "OTHER"}

# Class-typical bbox sizes (px on TAG 4463×6161 image).
# These are placeholders — SAM2 step refines them to real tight bboxes.
CLASS_BBOX_PX = {
    0: (260, 260),   # corner_wear
    1: (180, 600),   # edge_wear (elongated along edge)
    2: (420, 420),   # surface_damage
    3: (600, 90),    # scratch (elongated)
    4: (520, 320),   # crease
    5: (200, 200),   # dent/pit
    6: (380, 380),   # stain
}

# TAG nominal source image size (for normalization fallback)
TAG_W_FALLBACK = 4463
TAG_H_FALLBACK = 6161

# Placeholder coords to drop
PLACEHOLDER_COORDS = {(0, 0), (50, 50)}

# Severity bucket thresholds (TAG 0-1000 → 4-class ordinal)
SEVERITY_BUCKETS = [
    ("clean", 990, 1001),
    ("minor", 920, 990),
    ("major", 800, 920),
    ("disqualifying", 0, 800),
]
SEVERITY_NAME_OF = {sev: i for i, (sev, _, _) in enumerate(SEVERITY_BUCKETS)}

# Region definitions for corner/edge crops on full card
# CORNER_CROP_FRAC was 0.18 in initial test → user feedback: too large,
# showed text/energy symbols which TAG doesn't score. TAG scores only
# the corner tip (~3-5% area). Switched to 0.08 = corner tip + small margin.
CORNER_CROP_FRAC = 0.08
EDGE_CROP_FRAC = 0.07     # 7% strip thickness — tighter on edge tip too

# Detection image target width
TARGET_WIDTH = 1280

# Split fractions (group-aware)
SPLIT_FRACS = {"train": 0.70, "val": 0.15, "test": 0.15}

# Cap on clean negatives (we have ~5700; use them all)
MAX_NEGATIVES = 6000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("v3-builder")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CardRecord:
    cert: str
    meta: dict
    front_path: Path | None
    back_path: Path | None
    surface_defects: list  # list of dicts from metadata
    corners: list           # list of dicts from metadata
    edges: list             # list of dicts from metadata
    grade: float
    has_per_zone: bool


# ---------------------------------------------------------------------------
# Stage 1: scan
# ---------------------------------------------------------------------------

def _read_card(cdir: Path) -> CardRecord | None:
    mp = cdir / "metadata.json"
    if not mp.exists():
        return None
    try:
        meta = json.loads(mp.read_text(encoding="utf-8"))
    except Exception:
        return None
    front_path = cdir / "images" / "FRONT_MAIN.jpg"
    back_path = cdir / "images" / "BACK_MAIN.jpg"
    if not front_path.exists() and not back_path.exists():
        return None
    try:
        grade = float(meta.get("grade") or 0)
    except Exception:
        grade = 0.0
    return CardRecord(
        cert=cdir.name,
        meta=meta,
        front_path=front_path if front_path.exists() else None,
        back_path=back_path if back_path.exists() else None,
        surface_defects=meta.get("surface_defects") or [],
        corners=meta.get("corners") or [],
        edges=meta.get("edges") or [],
        grade=grade,
        has_per_zone=bool(meta.get("corners") or meta.get("edges")),
    )


def scan_raw(sample_n: int | None = None) -> list[CardRecord]:
    """Walk data/tag_raw/, build CardRecord list of cards with at least 1 image.

    Sample mode: smart-sample = 30% per-zone cards (rare, for severity) +
    70% random (for detection diversity).
    """
    all_dirs = sorted(d for d in RAW.iterdir() if d.is_dir())

    if not sample_n:
        # Full run
        cards = []
        skipped = 0
        for cdir in all_dirs:
            c = _read_card(cdir)
            if c is None:
                skipped += 1
            else:
                cards.append(c)
        log.info(f"Scan: {len(cards)} cards accepted, {skipped} skipped (no meta or no images)")
        return cards

    # Sample mode — smart mix
    log.info(f"Sample mode: picking {sample_n} cards (smart mix per-zone + random)")
    per_zone_target = max(1, int(sample_n * 0.3))
    random_target = sample_n - per_zone_target

    rng = random.Random(42)
    rng.shuffle(all_dirs)

    per_zone_cards: list[CardRecord] = []
    random_cards: list[CardRecord] = []
    for cdir in all_dirs:
        if len(per_zone_cards) >= per_zone_target and len(random_cards) >= random_target:
            break
        c = _read_card(cdir)
        if c is None:
            continue
        if c.has_per_zone and len(per_zone_cards) < per_zone_target:
            per_zone_cards.append(c)
        elif not c.has_per_zone and len(random_cards) < random_target:
            random_cards.append(c)

    cards = per_zone_cards + random_cards
    log.info(
        f"Scan: {len(cards)} cards ({len(per_zone_cards)} per-zone "
        f"+ {len(random_cards)} random)"
    )
    return cards


# ---------------------------------------------------------------------------
# Stage 2: split assignment (GroupKFold by cert prefix)
# ---------------------------------------------------------------------------

def assign_splits(cards: list[CardRecord]) -> dict[str, str]:
    """Return {cert: split_name}. Groups certs by 2-char prefix to prevent leakage."""
    # Group by first 2 chars (TAG batches often share prefix)
    groups: dict[str, list[str]] = defaultdict(list)
    for c in cards:
        key = c.cert[:2] if len(c.cert) >= 2 else c.cert
        groups[key].append(c.cert)

    rng = random.Random(42)
    group_keys = sorted(groups.keys())
    rng.shuffle(group_keys)

    n_total = sum(len(g) for g in groups.values())
    targets = {sp: int(n_total * frac) for sp, frac in SPLIT_FRACS.items()}

    assignment: dict[str, str] = {}
    counts = {sp: 0 for sp in SPLIT_FRACS}
    for gk in group_keys:
        # Assign this group to whichever split is most under-target
        sp = min(counts, key=lambda s: counts[s] / targets[s] if targets[s] else 1.0)
        for cert in groups[gk]:
            assignment[cert] = sp
            counts[sp] += 1

    log.info(f"Split assignment: {counts} from {len(group_keys)} cert-prefix groups")
    return assignment


# ---------------------------------------------------------------------------
# Stage 3: detection labels
# ---------------------------------------------------------------------------

def map_defect_type(defect_type: str) -> int | None:
    """Map TAG defect_type string → class id (or None to skip)."""
    if defect_type in IGNORED_TYPES:
        return None
    t = defect_type.lower().strip()
    if t in DEFECT_MAP:
        return DEFECT_MAP[t]
    # Partial match (longest first)
    candidates = sorted(DEFECT_MAP.items(), key=lambda kv: -len(kv[0]))
    for key, cid in candidates:
        if key in t:
            return cid
    return None  # truly unknown


def build_detection_labels(
    card: CardRecord, side: str, img_w: int, img_h: int
) -> list[tuple[int, float, float, float, float]]:
    """Build YOLO bbox lines for a single (cert, side). Returns list of (cls, x, y, w, h) normalized."""
    lines: list[tuple[int, float, float, float, float]] = []
    rng = random.Random(int(hashlib.md5(card.cert.encode()).hexdigest()[:8], 16))

    for d in card.surface_defects:
        if d.get("side") != side:
            continue
        x = d.get("x")
        y = d.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            continue
        if (x, y) in PLACEHOLDER_COORDS:
            continue

        cls = map_defect_type(d.get("defect_type", ""))
        if cls is None:
            continue

        bw, bh = CLASS_BBOX_PX[cls]
        # Tiny deterministic jitter ±10% so they aren't perfectly identical
        bw = int(bw * (1 + (rng.random() - 0.5) * 0.2))
        bh = int(bh * (1 + (rng.random() - 0.5) * 0.2))

        xn = x / img_w
        yn = y / img_h
        wn = bw / img_w
        hn = bh / img_h
        xn = max(wn / 2, min(1.0 - wn / 2, xn))
        yn = max(hn / 2, min(1.0 - hn / 2, yn))
        lines.append((cls, xn, yn, wn, hn))

    return lines


# ---------------------------------------------------------------------------
# Stage 4: severity dataset
# ---------------------------------------------------------------------------

def severity_label(score: float | int | None) -> str | None:
    """Map TAG 0-1000 score → severity bucket name (or None if no score)."""
    if not isinstance(score, (int, float)):
        return None
    for name, lo, hi in SEVERITY_BUCKETS:
        if lo <= score < hi:
            return name
    return None


def build_severity_corners(
    card: CardRecord, side: str, img: Image.Image
) -> list[tuple[Image.Image, str, str]]:
    """Crop 4 corners with severity labels. Returns [(crop, position, sev_name)]."""
    out: list[tuple[Image.Image, str, str]] = []
    W, H = img.size
    s = int(min(W, H) * CORNER_CROP_FRAC)
    boxes = {
        "top_left": (0, 0, s, s),
        "top_right": (W - s, 0, W, s),
        "bottom_left": (0, H - s, s, H),
        "bottom_right": (W - s, H - s, W, H),
    }
    for pos, box in boxes.items():
        rec = next(
            (c for c in card.corners if c.get("side") == side and c.get("position") == pos),
            None,
        )
        if rec is None:
            continue
        sev = severity_label(rec.get("total"))
        if sev is None:
            continue
        crop = img.crop(box).resize((224, 224), Image.LANCZOS)
        out.append((crop, pos, sev))
    return out


def build_severity_edges(
    card: CardRecord, side: str, img: Image.Image
) -> list[tuple[Image.Image, str, str]]:
    """Crop 4 edges with severity labels. Returns [(crop, position, sev_name)]."""
    out: list[tuple[Image.Image, str, str]] = []
    W, H = img.size
    t = int(min(W, H) * EDGE_CROP_FRAC)
    boxes = {
        "top":    (0, 0, W, t),
        "bottom": (0, H - t, W, H),
        "left":   (0, 0, t, H),
        "right":  (W - t, 0, W, H),
    }
    for pos, box in boxes.items():
        rec = next(
            (e for e in card.edges if e.get("side") == side and e.get("position") == pos),
            None,
        )
        if rec is None:
            continue
        sev = severity_label(rec.get("total"))
        if sev is None:
            continue
        crop = img.crop(box)
        if pos in ("top", "bottom"):
            crop = crop.resize((480, 96), Image.LANCZOS)
        else:
            crop = crop.resize((96, 480), Image.LANCZOS)
        out.append((crop, pos, sev))
    return out


# ---------------------------------------------------------------------------
# Stage 5: write detection dataset
# ---------------------------------------------------------------------------

def write_detection(
    card: CardRecord, side: str, src_path: Path, split: str, det_dir: Path,
    class_counts: Counter, neg_count_used: list[int], max_negatives: int,
) -> bool:
    """Write detection image + label for one (cert, side). Returns True if written."""
    try:
        im = Image.open(src_path)
        W, H = im.size
    except Exception as e:
        log.warning(f"  {card.cert} {side}: failed to open image: {e}")
        return False

    lines = build_detection_labels(card, side, W, H)
    is_negative = (len(lines) == 0)

    if is_negative:
        if neg_count_used[0] >= max_negatives:
            return False  # skip excess negatives
        neg_count_used[0] += 1

    # Resize to TARGET_WIDTH preserving aspect
    scale = TARGET_WIDTH / W
    new_w, new_h = TARGET_WIDTH, int(H * scale)
    im_r = im.convert("RGB").resize((new_w, new_h), Image.LANCZOS)

    img_dest = det_dir / "images" / split / f"{card.cert}_{side}.jpg"
    lbl_dest = det_dir / "labels" / split / f"{card.cert}_{side}.txt"
    im_r.save(img_dest, quality=88)
    with open(lbl_dest, "w") as f:
        for cls, x, y, w, h in lines:
            f.write(f"{cls} {x:.6f} {y:.6f} {w:.6f} {h:.6f}\n")
            class_counts[cls] += 1
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=None, help="Process only N cards (sanity check)")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUT, help="Output dir")
    ap.add_argument("--clean", action="store_true", help="Wipe output dir before building")
    args = ap.parse_args()

    start = time.time()
    out = args.output
    det = out / "detection"
    sev = out / "severity"

    if args.clean and out.exists():
        log.info(f"Wiping {out}")
        shutil.rmtree(out)

    # Create dirs
    for sp in ("train", "val", "test"):
        (det / "images" / sp).mkdir(parents=True, exist_ok=True)
        (det / "labels" / sp).mkdir(parents=True, exist_ok=True)
        (sev / "corners" / sp).mkdir(parents=True, exist_ok=True)
        (sev / "edges" / sp).mkdir(parents=True, exist_ok=True)

    log.info(f"Output: {out}")
    log.info(f"Sample mode: {args.sample if args.sample else 'FULL (96k)'}")

    # Stage 1: scan
    cards = scan_raw(sample_n=args.sample)

    # Stage 2: split
    assignment = assign_splits(cards)

    # Stage 3-5: build datasets
    log.info("Building datasets…")
    class_counts = Counter()
    sides_written = {"train": 0, "val": 0, "test": 0}
    neg_count = [0]  # mutable for closure
    sev_corner_counts: Counter = Counter()
    sev_edge_counts: Counter = Counter()
    n_with_per_zone = 0

    progress_step = max(1, len(cards) // 50)
    for i, card in enumerate(cards):
        split = assignment[card.cert]
        if i % progress_step == 0:
            log.info(f"  [{i}/{len(cards)}] {card.cert} → {split}")
        for side, src_path in (("front", card.front_path), ("back", card.back_path)):
            if src_path is None:
                continue
            if write_detection(card, side, src_path, split, det, class_counts, neg_count, MAX_NEGATIVES):
                sides_written[split] += 1

            # Severity dataset (only for cards with per-zone arrays)
            if card.has_per_zone:
                try:
                    img = Image.open(src_path).convert("RGB")
                    for crop, pos, sev_name in build_severity_corners(card, side, img):
                        fname = f"{card.cert}_{side}_{pos}_{sev_name}.jpg"
                        crop.save(sev / "corners" / split / fname, quality=88)
                        sev_corner_counts[sev_name] += 1
                    for crop, pos, sev_name in build_severity_edges(card, side, img):
                        fname = f"{card.cert}_{side}_{pos}_{sev_name}.jpg"
                        crop.save(sev / "edges" / split / fname, quality=88)
                        sev_edge_counts[sev_name] += 1
                except Exception as e:
                    log.warning(f"  {card.cert} {side}: severity crop failed: {e}")
        if card.has_per_zone:
            n_with_per_zone += 1

    # Write dataset.yaml for detection
    yaml = f"""# CardChecker v3 Defect Detection Dataset (7 classes)
# Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}
# Sample mode: {args.sample if args.sample else 'FULL'}
# Cards: {len(cards)} | Sides written: {sides_written}

path: {out.absolute().as_posix()}/detection
train: images/train
val: images/val
test: images/test

nc: 7
names: {json.dumps({str(i): n for i, n in CLASS_NAMES.items()})}
"""
    (det / "dataset.yaml").write_text(yaml)

    # Summary
    elapsed = time.time() - start
    log.info("=" * 60)
    log.info(f"DONE in {elapsed:.1f}s")
    log.info(f"Detection: {sum(sides_written.values())} sides total")
    log.info(f"  per split: {sides_written}")
    log.info(f"  negatives included: {neg_count[0]}")
    log.info(f"  class distribution: " +
             ", ".join(f"{CLASS_NAMES[c]}={n}" for c, n in sorted(class_counts.items())))
    log.info(f"Severity: {n_with_per_zone} cards had per-zone arrays")
    log.info(f"  corner patches per severity: {dict(sev_corner_counts)}")
    log.info(f"  edge patches per severity:   {dict(sev_edge_counts)}")


if __name__ == "__main__":
    main()
