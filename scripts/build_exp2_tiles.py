"""EXP-2 tiles — sampled to MATCH full-card sliding-window inference (fixes the tile->card gap).

Why: EXP-1 (de-centered 30-70% positives + interior-only negatives) cut the full-card flood
7x but still floods on borders/text/holo and recalls only ~3% on whole cards. Root cause =
train/inference distribution mismatch. Here we sample windows the way inference sees them:

  POSITIVE windows (from defected cards): defect point placed at a UNIFORM-RANDOM position in
    the 512 window (0..1, incl. edges) so the model fires wherever a defect lands in a window;
    label = ALL placeholder-filtered defect points of that side that fall inside the window
    (multi-point). Matches: at inference a defect can be anywhere in a swept window.
  NEGATIVE windows (from gem-mint clean cards only — trustworthy): sampled over the FULL card
    area incl. borders/corners/text/holo (x0 in [0, W-tile]), NOT just interior. This is the
    fix for the border/text flood. Empty label.

Label: positive = one "tx ty" line per defect point; negative = empty file.
Single channel downstream (train_defect_exp2.py).

Usage:
  python scripts/build_exp2_tiles.py --max-pos 40000 --max-neg 40000 --out data/tag_v5_tiles
"""
from __future__ import annotations
import argparse, json, re, random
from pathlib import Path
from collections import defaultdict
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


def split_for(cert):
    h = sum(ord(c) for c in cert) % 10
    return "train" if h < 8 else ("val" if h == 8 else "test")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/tag_v5_tiles"))
    ap.add_argument("--tile", type=int, default=512)
    ap.add_argument("--max-pos", type=int, default=40000)
    ap.add_argument("--max-neg", type=int, default=40000)
    ap.add_argument("--neg-per-card", type=int, default=20)
    ap.add_argument("--min-grade", type=float, default=9.0)
    ap.add_argument("--quality", type=int, default=90)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    T = args.tile
    for sp in ("train", "val", "test"):
        (args.out / "images" / sp).mkdir(parents=True, exist_ok=True)
        (args.out / "labels" / sp).mkdir(parents=True, exist_ok=True)
    manifest = open(args.out / "manifest.jsonl", "w")

    split_map = build_split_map()
    certs = sorted(split_map.keys()); rng.shuffle(certs)

    n_pos = n_neg = n_drop = 0

    # ---- POSITIVES: inference-matched windows (defect at random position, multi-point label) ----
    for cert in certs:
        if n_pos >= args.max_pos:
            break
        sp = split_map[cert]
        mp = RAW / cert / "metadata.json"
        if not mp.exists():
            continue
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        by_side = defaultdict(list)
        for d in (meta.get("surface_defects") or []):
            x, y = d.get("x"), d.get("y")
            if is_placeholder(x, y):
                n_drop += 1; continue
            by_side[d.get("side", "front")].append((x, y))
        for side, pts in by_side.items():
            if n_pos >= args.max_pos:
                break
            ip = RAW / cert / "images" / f"{side.upper()}_MAIN.jpg"
            if not ip.exists():
                continue
            try:
                im = Image.open(ip).convert("RGB")
            except Exception:
                continue
            W, H = im.size
            # pixel coords of all points on this side
            ppts = [(int(x / NOM_W * W), int(y / NOM_H * H)) for (x, y) in pts]
            for si, (px, py) in enumerate(ppts):
                if n_pos >= args.max_pos:
                    break
                # window with this point at a uniform-random offset in [0,tile)
                ox = rng.randint(0, T - 1); oy = rng.randint(0, T - 1)
                x0 = max(0, min(W - T, px - ox)); y0 = max(0, min(H - T, py - oy))
                # all points inside this window
                lines = []
                for (qx, qy) in ppts:
                    if x0 <= qx < x0 + T and y0 <= qy < y0 + T:
                        lines.append(f"{(qx-x0)/T:.6f} {(qy-y0)/T:.6f}")
                name = f"{cert}_{side}_p{si}"
                im.crop((x0, y0, x0 + T, y0 + T)).save(args.out / "images" / sp / f"{name}.jpg", quality=args.quality)
                (args.out / "labels" / sp / f"{name}.txt").write_text("\n".join(lines) + "\n")
                manifest.write(json.dumps({"tile": name, "cert": cert, "split": sp, "kind": "pos", "npts": len(lines)}) + "\n")
                n_pos += 1

    # ---- NEGATIVES: full-card-coverage windows from gem-mint clean cards ----
    target_neg = min(args.max_neg, n_pos)  # ~balanced
    for mp in RAW.glob("*/metadata.json"):
        if n_neg >= target_neg:
            break
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        g = meta.get("grade") or 0
        real = [d for d in (meta.get("surface_defects") or []) if not is_placeholder(d.get("x", 0), d.get("y", 0))]
        if g < args.min_grade or real:
            continue
        cert = mp.parent.name
        sp = split_map.get(cert) or split_for(cert)
        for side in ("front", "back"):
            if n_neg >= target_neg:
                break
            ip = RAW / cert / "images" / f"{side.upper()}_MAIN.jpg"
            if not ip.exists():
                continue
            try:
                im = Image.open(ip).convert("RGB")
            except Exception:
                continue
            W, H = im.size
            for k in range(args.neg_per_card):
                if n_neg >= target_neg:
                    break
                # FULL-card coverage incl borders/corners/text (no interior restriction)
                x0 = rng.randint(0, max(0, W - T)); y0 = rng.randint(0, max(0, H - T))
                name = f"{cert}_{side}_n{k}"
                im.crop((x0, y0, x0 + T, y0 + T)).save(args.out / "images" / sp / f"{name}.jpg", quality=args.quality)
                (args.out / "labels" / sp / f"{name}.txt").write_text("")
                manifest.write(json.dumps({"tile": name, "cert": cert, "split": sp, "kind": "neg"}) + "\n")
                n_neg += 1

    manifest.close()
    print("=" * 56)
    print(f"positives: {n_pos} (multi-point windows)  negatives: {n_neg}  dropped placeholders: {n_drop}")
    print(f"out: {args.out}")


if __name__ == "__main__":
    main()
