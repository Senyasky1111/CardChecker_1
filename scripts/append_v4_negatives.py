"""Append more trustworthy NEGATIVE tiles to data/tag_v4_tiles.

The initial build exhausted gem-mint cards at ~3.8k negatives (vs ~87k positives) — too
imbalanced to teach "clean". Here we take MORE crops per clean card and relax grade>=9.0
(still 0 real defects) to reach ~target negatives. Diversity is capped by #clean cards, so
we sample multiple non-overlapping-ish crops each.

Negatives = empty label files (downstream all-zero target). Split by cert hash.
"""
from __future__ import annotations
import argparse, json, random
from pathlib import Path
from PIL import Image

RAW = Path("data/tag_raw")
OUT = Path("data/tag_v4_tiles")


def is_placeholder(x, y, r=25):
    return (abs(x - 50) <= r and abs(y - 50) <= r) or (abs(x) <= r and abs(y) <= r)


def split_for(cert):
    h = sum(ord(c) for c in cert) % 10
    return "train" if h < 8 else ("val" if h == 8 else "test")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=30000, help="ADDITIONAL negatives to add")
    ap.add_argument("--per-card", type=int, default=12)
    ap.add_argument("--min-grade", type=float, default=9.0)
    ap.add_argument("--tile", type=int, default=512)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    # certs already used as negatives (have *_n*.txt) — skip to maximize card diversity first
    used = set()
    for lp in OUT.glob("labels/*/*_n*.txt"):
        used.add(lp.stem.split("_")[0])

    added = 0
    scanned = 0
    for mp in RAW.glob("*/metadata.json"):
        if added >= args.target:
            break
        scanned += 1
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        g = meta.get("grade") or 0
        real = [d for d in (meta.get("surface_defects") or [])
                if not is_placeholder(d.get("x", 0), d.get("y", 0))]
        if g < args.min_grade or real:
            continue
        cert = mp.parent.name
        side = "front"
        ip = RAW / cert / "images" / f"{side.upper()}_MAIN.jpg"
        if not ip.exists():
            continue
        try:
            im = Image.open(ip).convert("RGB")
        except Exception:
            continue
        W, H = im.size
        sp = split_for(cert)
        # if cert already used for negatives, continue numbering its crops
        start = 2 if cert in used else 0
        for k in range(start, start + args.per_card):
            if added >= args.target:
                break
            x0 = rng.randint(int(0.04 * W), max(int(0.04 * W), W - args.tile - int(0.04 * W)))
            y0 = rng.randint(int(0.04 * H), max(int(0.04 * H), H - args.tile - int(0.04 * H)))
            name = f"{cert}_{side}_n{k}"
            (OUT / "images" / sp / f"{name}.jpg").exists() and None
            im.crop((x0, y0, x0 + args.tile, y0 + args.tile)).save(
                OUT / "images" / sp / f"{name}.jpg", quality=90)
            (OUT / "labels" / sp / f"{name}.txt").write_text("")
            added += 1
        if scanned % 2000 == 0:
            print(f"  scanned={scanned} added={added}", flush=True)

    # report final counts
    tot_neg = len(list(OUT.glob("labels/*/*_n*.txt")))
    print(f"added {added} negatives (scanned {scanned} cards). total negatives now: {tot_neg}")


if __name__ == "__main__":
    main()
