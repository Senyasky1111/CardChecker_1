"""EXP-1 tile rebuild — fixes the data flaws the stress-test + EXP-0 exposed.

Differences vs export_native_tiles.py (the v3 export that produced the flooding model):
  1. PLACEHOLDER FILTER: drop the ~11% junk points within r=25px of (50,50)/(0,0)
     (the old export only dropped EXACT (0,0)/(50,50), so junk leaked into ~11% of tiles).
  2. DE-CENTERED positives: the defect point lands at a RANDOM position inside the tile
     (central 30-70% band), not always at the center. Kills the center-prior that made the
     model fire at every sliding-window center.
  3. CLASS-AGNOSTIC: single "defect" label (no 7-class split). Type is a later step.
  4. TRUSTWORTHY NEGATIVES: clean tiles are sampled ONLY from gem-mint (grade>=9.5, 0-defect)
     cards. We do NOT sample "far from a point" on damaged cards as negative, because TAG
     labels are CAPPED/non-exhaustive -> that background often hides real unlabeled defects.

Output: data/tag_v4_tiles/{images,labels}/{train,val,test}/
  positive label file: one line "tx_norm ty_norm"
  negative label file: empty (0 bytes) -> all-zero heatmap target downstream
Split reuses the tag_v3 detection GroupKFold assignment (no leakage); clean cards (no points)
are split deterministically by cert hash.

Usage:
  ./venv/Scripts/python.exe scripts/build_exp1_tiles.py --sample 400 --out data/_v4_dryrun   # dry
  ./venv/Scripts/python.exe scripts/build_exp1_tiles.py --out data/tag_v4_tiles               # full
"""
from __future__ import annotations
import argparse, json, re, random
from pathlib import Path
from collections import Counter, defaultdict
from PIL import Image

RAW = Path("data/tag_raw")
V3 = Path("data/tag_v3/detection")
NOM_W, NOM_H = 4463, 6161


def is_placeholder(x, y, r=25):
    return (abs(x - 50) <= r and abs(y - 50) <= r) or (abs(x) <= r and abs(y) <= r)


def build_split_map():
    m = {}
    rex = re.compile(r"([A-Z0-9]+)_(front|back)$")
    for sp in ("train", "val", "test"):
        d = V3 / "images" / sp
        if not d.exists():
            continue
        for p in d.glob("*.jpg"):
            mm = rex.match(p.stem)
            if mm:
                m[mm.group(1)] = sp
    return m


def split_for_clean(cert):
    """deterministic split for clean cards (not in the defect split): hash by cert."""
    h = sum(ord(c) for c in cert) % 10
    return "train" if h < 8 else ("val" if h == 8 else "test")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/tag_v4_tiles"))
    ap.add_argument("--tile", type=int, default=512)
    ap.add_argument("--neg-ratio", type=float, default=1.0, help="negatives per positive")
    ap.add_argument("--center-band", type=float, default=0.30,
                    help="point kept within [band, 1-band] of tile (de-centering range)")
    ap.add_argument("--sample", type=int, default=None, help="dry run: ~N positives then stop")
    ap.add_argument("--quality", type=int, default=90)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    split_map = build_split_map()
    print(f"defect-split certs: {len(split_map)}")
    for sp in ("train", "val", "test"):
        (args.out / "images" / sp).mkdir(parents=True, exist_ok=True)
        (args.out / "labels" / sp).mkdir(parents=True, exist_ok=True)
    manifest = open(args.out / "manifest.jsonl", "w")

    half = args.tile // 2
    n_pos = n_neg = 0
    n_drop_ph = 0
    split_pos = Counter()
    certs = sorted(split_map.keys())
    rng.shuffle(certs)  # so a --sample/--max cap covers all splits, not just the first certs

    # ---- PASS 1: positive (de-centered) tiles from defected cards ----
    stop = False
    for cert in certs:
        if stop:
            break
        sp = split_map[cert]
        mp = RAW / cert / "metadata.json"
        if not mp.exists():
            continue
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        defects = meta.get("surface_defects") or []
        by_side = defaultdict(list)
        for d in defects:
            x, y = d.get("x"), d.get("y")
            if is_placeholder(x, y):
                n_drop_ph += 1
                continue
            by_side[d.get("side", "front")].append((x, y))
        for side, pts in by_side.items():
            img_path = RAW / cert / "images" / f"{side.upper()}_MAIN.jpg"
            if not img_path.exists():
                continue
            try:
                im = Image.open(img_path).convert("RGB")
            except Exception:
                continue
            W, H = im.size
            for i, (x, y) in enumerate(pts):
                px, py = int(x / NOM_W * W), int(y / NOM_H * H)
                # de-center: choose where in the tile the point should land
                fx = rng.uniform(args.center_band, 1 - args.center_band)
                fy = rng.uniform(args.center_band, 1 - args.center_band)
                x0 = int(px - fx * args.tile); y0 = int(py - fy * args.tile)
                x0 = max(0, min(W - args.tile, x0)); y0 = max(0, min(H - args.tile, y0))
                tile = im.crop((x0, y0, x0 + args.tile, y0 + args.tile))
                tx, ty = px - x0, py - y0
                name = f"{cert}_{side}_p{i}"
                tile.save(args.out / "images" / sp / f"{name}.jpg", quality=args.quality)
                (args.out / "labels" / sp / f"{name}.txt").write_text(
                    f"{tx/args.tile:.6f} {ty/args.tile:.6f}\n")
                manifest.write(json.dumps({"tile": name, "cert": cert, "side": side,
                    "split": sp, "kind": "pos", "tile_xy": [tx, ty]}) + "\n")
                n_pos += 1; split_pos[sp] += 1
                if args.sample and n_pos >= args.sample:
                    stop = True; break
            if stop:
                break

    # ---- PASS 2: trustworthy negatives from gem-mint clean cards ----
    target_neg = int(n_pos * args.neg_ratio)
    print(f"positives={n_pos} (dropped {n_drop_ph} placeholder pts); sampling ~{target_neg} negatives from clean cards")
    for mp in RAW.glob("*/metadata.json"):
        if n_neg >= target_neg:
            break
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        g = meta.get("grade") or 0
        real = [d for d in (meta.get("surface_defects") or [])
                if not is_placeholder(d.get("x", 0), d.get("y", 0))]
        if g < 9.5 or real:
            continue
        cert = mp.parent.name
        sp = split_map.get(cert) or split_for_clean(cert)
        side = "front"
        img_path = RAW / cert / "images" / f"{side.upper()}_MAIN.jpg"
        if not img_path.exists():
            continue
        try:
            im = Image.open(img_path).convert("RGB")
        except Exception:
            continue
        W, H = im.size
        # 2 random clean crops per clean card (avoid extreme borders/background)
        for k in range(2):
            if n_neg >= target_neg:
                break
            x0 = rng.randint(int(0.05 * W), max(int(0.05 * W), W - args.tile - int(0.05 * W)))
            y0 = rng.randint(int(0.05 * H), max(int(0.05 * H), H - args.tile - int(0.05 * H)))
            tile = im.crop((x0, y0, x0 + args.tile, y0 + args.tile))
            name = f"{cert}_{side}_n{k}"
            tile.save(args.out / "images" / sp / f"{name}.jpg", quality=args.quality)
            (args.out / "labels" / sp / f"{name}.txt").write_text("")  # empty = negative
            manifest.write(json.dumps({"tile": name, "cert": cert, "side": side,
                "split": sp, "kind": "neg"}) + "\n")
            n_neg += 1

    manifest.close()
    print("=" * 56)
    print(f"positives: {n_pos}  {dict(split_pos)}")
    print(f"negatives: {n_neg}")
    print(f"dropped placeholder points: {n_drop_ph}")
    print(f"out: {args.out}")


if __name__ == "__main__":
    main()
