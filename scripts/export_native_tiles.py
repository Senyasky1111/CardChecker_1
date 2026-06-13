"""Re-export native-resolution defect tiles from TAG 4463x6161 originals.

For each defect point (x,y) in a card's metadata, crop a TILE_PX window centered
on the point from the FULL-RES original (data/tag_raw/<cert>/images/FRONT_MAIN.jpg),
NOT the 1280px downsample. This preserves hairline-defect signal the 1280px set destroys.

Output: data/tag_v3_tiles/{train,val,test}/  with:
  - images/<cert>_<side>_<i>.jpg   (TILE_PX tile)
  - labels/<cert>_<side>_<i>.txt   (point in tile coords + class; heatmap built downstream)
Plus a manifest.jsonl mapping each tile → (cert, side, defect class, orig xy, tile bbox).

Split assignment reuses the GroupKFold split already computed in tag_v3/detection
(by reading which split each cert landed in), so no leakage vs the existing split.

Usage:
  # dry run to check size
  python scripts/export_native_tiles.py --sample 1000 --out data/_tiles_dryrun
  # full
  python scripts/export_native_tiles.py --out data/tag_v3_tiles
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
from collections import Counter, defaultdict
from PIL import Image

RAW = Path("data/tag_raw")
V3  = Path("data/tag_v3/detection")   # to reuse split assignment
PLACEHOLDER = {(0, 0), (50, 50)}

# 7-class taxonomy (same mapping as build_v3_dataset)
DEFECT_MAP = {
    "corner wear": 0, "edge wear": 1,
    "surface / play wear": 2, "play wear defect": 2, "surface / surface defect": 2,
    "surface / ink defect": 2, "ink/surface defect": 2, "ink defect": 2,
    "surface / print line": 2, "print line(s)": 2, "surface / print line(s)": 2,
    "print line": 2, "surface / print defect": 2, "print defect": 2,
    "surface / roller mark": 2, "roller mark": 2, "surface / other damage": 2,
    "surface / scratch(es)": 3, "scratch(es)": 3, "surface / scratch": 3,
    "surface / scratches": 3, "scratches": 3, "surface / scuffing": 3, "scuffing": 3,
    "crease": 4, "surface / crease": 4, "wrinkle/crease": 4,
    "surface / wrinkle/crease": 4, "edge/corner / bend": 4, "bend": 4,
    "dent": 5, "surface / dent": 5, "pit": 5, "surface / pit": 5,
    "surface / pits": 5, "pits": 5,
    "stain": 6, "surface / stain": 6, "water/stain": 6,
    "surface / whitening": 6, "whitening": 6, "surface / water/stain": 6,
    "water/stain damage": 6, "surface / water damage": 6,
}
def map_class(t: str):
    t = t.lower().strip()
    if t in DEFECT_MAP: return DEFECT_MAP[t]
    for k, v in DEFECT_MAP.items():
        if k in t: return v
    return 2  # default surface_damage

TAG_W, TAG_H = 4463, 6161  # nominal; we use actual image size per file


def build_split_map():
    """cert -> split, from the existing tag_v3 detection split."""
    m = {}
    stem_re = re.compile(r"([A-Z0-9]+)_(front|back)$")
    for sp in ("train", "val", "test"):
        d = V3 / "images" / sp
        if not d.exists(): continue
        for p in d.glob("*.jpg"):
            mm = stem_re.match(p.stem)
            if mm: m[mm.group(1)] = sp
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/tag_v3_tiles"))
    ap.add_argument("--tile", type=int, default=512, help="tile size px at native res")
    ap.add_argument("--sample", type=int, default=None, help="dry-run: only N tiles")
    ap.add_argument("--quality", type=int, default=90)
    args = ap.parse_args()

    split_map = build_split_map()
    print(f"split map: {len(split_map)} certs assigned")

    for sp in ("train", "val", "test"):
        (args.out / "images" / sp).mkdir(parents=True, exist_ok=True)
        (args.out / "labels" / sp).mkdir(parents=True, exist_ok=True)
    manifest = open(args.out / "manifest.jsonl", "w")

    half = args.tile // 2
    n_tiles = 0
    n_cards = 0
    skipped_noimg = 0
    cls_count = Counter()
    split_count = Counter()
    bytes_total = 0

    certs = sorted(split_map.keys())
    stop = False
    for cert in certs:
        if stop: break
        sp = split_map[cert]
        mp = RAW / cert / "metadata.json"
        if not mp.exists(): continue
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        defects = meta.get("surface_defects") or []
        if not defects:
            continue
        # group by side
        by_side = defaultdict(list)
        for d in defects:
            if (d.get("x"), d.get("y")) in PLACEHOLDER: continue
            by_side[d.get("side", "front")].append(d)
        for side, ds in by_side.items():
            img_path = RAW / cert / "images" / f"{side.upper()}_MAIN.jpg"
            if not img_path.exists():
                skipped_noimg += 1
                continue
            try:
                im = Image.open(img_path).convert("RGB")
            except Exception:
                skipped_noimg += 1
                continue
            W, H = im.size
            for i, d in enumerate(ds):
                cls = map_class(d.get("defect_type", ""))
                # actual pixel pos in THIS image
                px = int(d["x"] / TAG_W * W)
                py = int(d["y"] / TAG_H * H)
                x0 = max(0, min(W - args.tile, px - half))
                y0 = max(0, min(H - args.tile, py - half))
                tile = im.crop((x0, y0, x0 + args.tile, y0 + args.tile))
                # point position within tile
                tx = px - x0
                ty = py - y0
                name = f"{cert}_{side}_{i}"
                outp = args.out / "images" / sp / f"{name}.jpg"
                tile.save(outp, quality=args.quality)
                bytes_total += outp.stat().st_size
                # label: class + normalized point (for FIDT/heatmap downstream)
                (args.out / "labels" / sp / f"{name}.txt").write_text(
                    f"{cls} {tx/args.tile:.6f} {ty/args.tile:.6f}\n")
                manifest.write(json.dumps({
                    "tile": name, "cert": cert, "side": side, "split": sp,
                    "cls": cls, "defect_type": d.get("defect_type"),
                    "orig_xy": [px, py], "tile_xy": [tx, ty],
                    "tile_box": [x0, y0, x0 + args.tile, y0 + args.tile],
                    "img_size": [W, H],
                }) + "\n")
                cls_count[cls] += 1
                split_count[sp] += 1
                n_tiles += 1
                if args.sample and n_tiles >= args.sample:
                    stop = True
                    break
            if stop: break
        n_cards += 1

    manifest.close()
    _report(n_tiles, n_cards, skipped_noimg, cls_count, split_count, bytes_total, args)


def _report(n_tiles, n_cards, skipped, cls_count, split_count, bytes_total, args):
    CLASSES = ["corner_wear","edge_wear","surface_damage","scratch","crease","dent","stain"]
    print("=" * 60)
    print(f"tiles: {n_tiles} from {n_cards} cards ({skipped} sides skipped no-image)")
    print(f"splits: {dict(split_count)}")
    print("class dist:")
    for c in range(7):
        print(f"  {CLASSES[c]:16} {cls_count[c]}")
    if n_tiles:
        avg = bytes_total / n_tiles
        print(f"avg tile size: {avg/1024:.1f} KB")
        print(f"this batch total: {bytes_total/1e9:.2f} GB")
        # extrapolate to full 95k
        print(f"EXTRAPOLATED to ~95,000 tiles: {avg*95000/1e9:.1f} GB")


if __name__ == "__main__":
    main()
