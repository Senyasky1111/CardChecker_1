"""Automatic CENTERING estimator + visual overlay vs TAG ground truth.

Pipeline (pure geometry, no training — the Step-4 centering v0):
  1. detect CARD box: color-distance from the 4 image corners (card on uniform holder bg).
  2. detect INNER-FRAME box: from just inside each card edge, sample the border color, then
     scan inward until the local color departs from it (border -> content transition).
  3. centering = opposing border-margin ratios: L% = left/(left+right), T% = top/(top+bottom).
  4. draw overlay (green=card, cyan=detected frame) + my% vs TAG% + error, and report MAE.

Usage:
  ./venv/Scripts/python.exe scripts/centering_overlay.py --dir runs/defect_full/llm_eval/claude_test
  ./venv/Scripts/python.exe scripts/centering_overlay.py --build N   # export N fresh front cards w/ GT first
"""
from __future__ import annotations
import argparse, glob, json, os, random, re
import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

OUT = "runs/defect_full/llm_eval/centering_overlay"
NOM_W, NOM_H = 4463, 6161


def parse_ratio(s):
    if not s or "/" not in str(s):
        return None
    try:
        a, b = str(s).split("/")
        a = float(re.sub(r"[^0-9.]", "", a)); b = float(re.sub(r"[^0-9.]", "", b))
        if 90 <= a + b <= 110:
            return [round(a, 1), round(b, 1)]
    except Exception:
        return None
    return None


def detect_card_box(a):
    H, W = a.shape[:2]; c = 12
    corners = np.concatenate([a[:c, :c].reshape(-1, 3), a[:c, -c:].reshape(-1, 3),
                              a[-c:, :c].reshape(-1, 3), a[-c:, -c:].reshape(-1, 3)])
    bg = np.median(corners, 0)
    mask = np.sqrt(((a - bg) ** 2).sum(-1)) > 38
    col = mask.mean(0); row = mask.mean(1)
    xs = np.where(col > 0.5)[0]; ys = np.where(row > 0.5)[0]
    if len(xs) < 5 or len(ys) < 5:
        return 0, 0, W - 1, H - 1
    return xs[0], ys[0], xs[-1], ys[-1]


def _smooth(v, k=5):
    ker = np.ones(k) / k
    return np.convolve(v, ker, mode="same")


def _edge_peak(grad_prof, lo_frac=0.015, hi_frac=0.34):
    """grad_prof: gradient magnitude vs distance-from-card-edge (index 0 = card edge).
    Return index of the strongest internal line within [lo,hi] of the search window =
    the inner frame edge. Skips the immediate card-edge spike."""
    n = len(grad_prof)
    lo, hi = int(lo_frac * n / 0.34), int(hi_frac * n / 0.34)
    lo = max(lo, int(0.04 * n)); hi = min(hi, n - 2)
    if hi <= lo:
        return n // 6
    seg = _smooth(grad_prof)[lo:hi]
    return lo + int(np.argmax(seg))


def detect_frame_box(a, card, max_frac=0.34):
    cl, ct, cr, cb = card
    cw, ch = cr - cl, cb - ct
    g = a.mean(2)
    midx0, midx1 = cl + int(0.30 * cw), cl + int(0.70 * cw)
    midy0, midy1 = ct + int(0.30 * ch), ct + int(0.70 * ch)
    mx = max(8, int(max_frac * cw)); my = max(8, int(max_frac * ch))
    gx = np.abs(np.diff(g, axis=1))  # vertical edges
    gy = np.abs(np.diff(g, axis=0))  # horizontal edges
    # left: mean vertical-edge strength per column over central rows, scanning inward
    fl = cl + _edge_peak(gx[midy0:midy1, cl:cl + mx].mean(0))
    fr = cr - _edge_peak(gx[midy0:midy1, cr - mx:cr].mean(0)[::-1])
    ft = ct + _edge_peak(gy[ct:ct + my, midx0:midx1].mean(1))
    fb = cb - _edge_peak(gy[cb - my:cb, midx0:midx1].mean(1)[::-1])
    return fl, ft, fr, fb


def build_set(n):
    os.makedirs(OUT, exist_ok=True)
    paths = glob.glob("data/tag_raw/*/metadata.json"); random.Random(5).shuffle(paths)
    gt = {}; k = 0
    for p in paths:
        if k >= n:
            break
        cert = os.path.basename(os.path.dirname(p))
        ip = f"data/tag_raw/{cert}/images/FRONT_MAIN.jpg"
        if not os.path.exists(ip):
            continue
        try:
            meta = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        lr = parse_ratio(meta.get("centering_front_lr")); tb = parse_ratio(meta.get("centering_front_tb"))
        if not lr or not tb:
            continue
        k += 1
        img = Image.open(ip).convert("RGB"); img.thumbnail((1100, 1100))
        name = f"c_{k:02d}.jpg"; img.save(f"{OUT}/{name}", quality=92)
        gt[name] = {"cert": cert, "grade": meta.get("grade"), "centering_lr": lr, "centering_tb": tb}
    json.dump(gt, open(f"{OUT}/_gt.json", "w"), indent=2)
    print(f"built {k} cards in {OUT}")
    return OUT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=OUT)
    ap.add_argument("--build", type=int, default=0)
    args = ap.parse_args()
    d = build_set(args.build) if args.build else args.dir
    gt = json.load(open(f"{d}/_gt.json"))
    os.makedirs(OUT, exist_ok=True)

    rows, lr_err, tb_err = [], [], []
    for k in sorted(gt):
        img = Image.open(f"{d}/{k}").convert("RGB")
        a = np.asarray(img, np.float32); W, H = img.size
        cl, ct, cr, cb = detect_card_box(a)
        fl, ft, fr, fb = detect_frame_box(a, (cl, ct, cr, cb))
        ml, mr = fl - cl, cr - fr
        mt, mb = ft - ct, cb - fb
        myL = 100 * ml / max(ml + mr, 1); myT = 100 * mt / max(mt + mb, 1)
        g = gt[k]; gL, gT = g["centering_lr"][0], g["centering_tb"][0]
        lr_err.append(abs(myL - gL)); tb_err.append(abs(myT - gT))
        rows.append((k, img, (cl, ct, cr, cb), (fl, ft, fr, fb), myL, myT, gL, gT))

    n = len(rows); cols = 4; r = (n + cols - 1) // cols
    fig, axes = plt.subplots(r, cols, figsize=(cols * 3.0, r * 3.9))
    axes = np.array(axes).reshape(-1)
    for ax in axes:
        ax.axis("off")
    for i, (k, img, (cl, ct, cr, cb), (fl, ft, fr, fb), myL, myT, gL, gT) in enumerate(rows):
        ax = axes[i]; ax.imshow(img)
        ax.add_patch(mpatches.Rectangle((cl, ct), cr - cl, cb - ct, fill=False, ec="#34c759", lw=1.4))
        ax.add_patch(mpatches.Rectangle((fl, ft), fr - fl, fb - ft, fill=False, ec="#00e5ff", lw=1.4))
        ax.set_title(f"{k}  L/R {myL:.0f}/{100-myL:.0f} vs TAG {gL:.0f}/{100-gL:.0f} (Δ{abs(myL-gL):.0f})\n"
                     f"T/B {myT:.0f}/{100-myT:.0f} vs TAG {gT:.0f}/{100-gT:.0f} (Δ{abs(myT-gT):.0f})", fontsize=7)
    fig.suptitle("Auto centering: green=card edge, cyan=detected inner frame. vs TAG ratios.", fontsize=11)
    fig.tight_layout()
    p = f"{OUT}/centering_grid.png"; fig.savefig(p, dpi=120, bbox_inches="tight")
    print(f"saved {p}")
    print(f"AUTO centering  L/R MAE = {np.mean(lr_err):.1f} pp   T/B MAE = {np.mean(tb_err):.1f} pp   (n={len(rows)})")
    print(f"  within 3pp: L/R {np.mean(np.array(lr_err)<=3)*100:.0f}%  T/B {np.mean(np.array(tb_err)<=3)*100:.0f}%")


if __name__ == "__main__":
    main()
