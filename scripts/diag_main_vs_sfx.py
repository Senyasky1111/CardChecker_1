"""Diagnostic: are TAG defect points REAL? Show zoomed crops around each defect point
on the flat MAIN image vs the raking-light SFX image, side by side, labeled by type.

If labels were garbage/misaligned, the SFX crop would show nothing at the marked point.
If labels are real-but-flat-invisible, the defect pops in SFX and is faint in MAIN.

Usage:
  ./venv/Scripts/python.exe scripts/diag_main_vs_sfx.py --n 18 --win 320
"""
from __future__ import annotations
import argparse, glob, json, os, random
import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

NOM_W, NOM_H = 4463, 6161
OUT = "runs/defect_full/viz"


def is_placeholder(x, y, r=25):
    """TAG dumps ~11% of points at a default near (50,50) (and a few at (0,0)) — not real
    defect locations. Drop anything within r px of those anchors."""
    return (abs(x - 50) <= r and abs(y - 50) <= r) or (abs(x) <= r and abs(y) <= r)
# prefer the "invisible in flat" surface defects for the most convincing comparison
PRIORITY = ("scratch", "ink", "print", "dent", "crease", "play wear", "stain", "roller")


def find_cards_with_sfx(limit_scan=4000):
    out = []
    for mp in glob.glob("data/tag_raw/*/metadata.json")[:limit_scan]:
        cert = os.path.basename(os.path.dirname(mp))
        for side in ("FRONT", "BACK"):
            main = f"data/tag_raw/{cert}/images/{side}_MAIN.jpg"
            sfx = f"data/tag_raw/{cert}/images/{side}_SFX.jpg"
            if os.path.exists(main) and os.path.exists(sfx):
                out.append((cert, side.lower(), mp))
    return out


def collect_defects(n, win):
    cards = find_cards_with_sfx()
    random.Random(2).shuffle(cards)
    picked = []
    # two passes: priority (surface) defects first, then anything
    for prio in (True, False):
        for cert, side, mp in cards:
            if len(picked) >= n:
                break
            try:
                meta = json.load(open(mp, encoding="utf-8"))
            except Exception:
                continue
            ds = [d for d in (meta.get("surface_defects") or [])
                  if d.get("side", "front") == side and not is_placeholder(d.get("x", 0), d.get("y", 0))]
            for d in ds:
                t = (d.get("defect_type") or "").lower()
                is_prio = any(k in t for k in PRIORITY)
                if prio and not is_prio:
                    continue
                picked.append((cert, side, d["x"], d["y"], d.get("defect_type", "?")))
                break  # one defect per card for variety
        if len(picked) >= n:
            break
    return picked[:n]


def crop(img, x, y, win):
    W, H = img.size
    px, py = int(x / NOM_W * W), int(y / NOM_H * H)
    box = (max(0, px - win), max(0, py - win), min(W, px + win), min(H, py + win))
    c = img.crop(box)
    # point position within crop
    return c, (px - box[0], py - box[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=18)
    ap.add_argument("--win", type=int, default=320, help="half-size of zoom window (native px)")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    defects = collect_defects(args.n, args.win)
    print(f"collected {len(defects)} defects with MAIN+SFX")

    rows = len(defects)
    fig, axes = plt.subplots(rows, 2, figsize=(8, rows * 3.4))
    if rows == 1:
        axes = axes.reshape(1, 2)
    for i, (cert, side, x, y, dtype) in enumerate(defects):
        main = Image.open(f"data/tag_raw/{cert}/images/{side.upper()}_MAIN.jpg").convert("RGB")
        sfx = Image.open(f"data/tag_raw/{cert}/images/{side.upper()}_SFX.jpg").convert("RGB")
        for j, (img, name) in enumerate([(main, "MAIN (flat)"), (sfx, "SFX (raking light)")]):
            c, (cx, cy) = crop(img, x, y, args.win)
            ax = axes[i, j]
            ax.imshow(c)
            ax.add_patch(mpatches.Circle((cx, cy), max(18, args.win // 12), fill=False,
                                         ec="#ff2d55", lw=2.2))
            ax.set_xticks([]); ax.set_yticks([])
            if j == 0:
                ax.set_ylabel(f"{cert}\n{dtype}", fontsize=7, rotation=0, ha="right", va="center")
            if i == 0:
                ax.set_title(name, fontsize=10)
        print(f"  {i+1}/{rows} {cert} {side} {dtype}", flush=True)
    fig.suptitle("Same TAG point on flat MAIN vs raking-light SFX (red ring = labeled defect)",
                 fontsize=11, y=1.0)
    fig.tight_layout()
    p = os.path.join(OUT, "main_vs_sfx_grid.png")
    fig.savefig(p, dpi=120, bbox_inches="tight")
    print(f"saved {p}")


if __name__ == "__main__":
    main()
