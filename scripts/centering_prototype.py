"""Centering prototype + validation against TAG ground-truth ratios ($0, no UI).

TAG MAIN images are already ~top-down, so this isolates the hard part — INNER-FRAME detection
and the centering math — and scores it against TAG's centering_front_lr / _tb.

Inner-frame detection = "long straight gradient line" (not argmax): within a search band inward
from each outer card edge, find the row/col where a strong gradient persists across MOST of the
card span (a real frame line is long; text/holo gradients are short) -> robust seed line.

Centering: left border = innerL - outerL, right border = outerR - innerR;  L% = L/(L+R)*100.
Worst axis drives the grade (PSA/TAG convention).

Usage:
  ./venv/Scripts/python.exe scripts/centering_prototype.py --n 24
"""
from __future__ import annotations
import argparse, glob, json, os, random, re
import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

OUT = "runs/centering_proto"
NOM_W, NOM_H = 4463, 6161


def parse_ratio(s):
    if not s or "/" not in str(s):
        return None
    try:
        a, b = str(s).split("/")
        a = float(re.sub(r"[^0-9.]", "", a)); b = float(re.sub(r"[^0-9.]", "", b))
        if 90 <= a + b <= 110:
            return (a, b)
    except Exception:
        return None
    return None


def detect_card_box(a):
    """outer card edges via color-distance from image corners (card on holder bg)."""
    H, W = a.shape[:2]; c = 14
    corners = np.concatenate([a[:c, :c].reshape(-1, 3), a[:c, -c:].reshape(-1, 3),
                              a[-c:, :c].reshape(-1, 3), a[-c:, -c:].reshape(-1, 3)])
    bg = np.median(corners, 0)
    mask = np.sqrt(((a - bg) ** 2).sum(-1)) > 40
    col = mask.mean(0); row = mask.mean(1)
    xs = np.where(col > 0.5)[0]; ys = np.where(row > 0.5)[0]
    if len(xs) < 5 or len(ys) < 5:
        return 0, 0, W - 1, H - 1
    return int(xs[0]), int(ys[0]), int(xs[-1]), int(ys[-1])


def inner_line(grad, axis, lo, hi, span_lo, span_hi, frac=0.5):
    """Find the row/col in [lo,hi] whose strong-gradient pixels span the most of [span_lo,span_hi].
    axis='v' -> vertical line (scan columns, gradient gx); axis='h' -> horizontal (rows, gy)."""
    if hi <= lo:
        return lo
    if axis == 'v':
        band = grad[span_lo:span_hi, lo:hi]            # (rows, cols)
        thr = np.percentile(band, 75)
        score = (band > max(thr, 1e-3)).mean(axis=0)   # per-col fraction of strong-grad rows
    else:
        band = grad[lo:hi, span_lo:span_hi]            # (rows, cols)
        thr = np.percentile(band, 75)
        score = (band > max(thr, 1e-3)).mean(axis=1)   # per-row fraction
    # smooth
    k = 5; score = np.convolve(score, np.ones(k) / k, mode="same")
    idx = int(np.argmax(score))
    return lo + idx, float(score[idx])


def measure(a, max_frac=0.30):
    H, W = a.shape[:2]
    cl, ct, cr, cb = detect_card_box(a)
    cw, ch = cr - cl, cb - ct
    g = a.mean(2)
    gx = np.abs(np.diff(g, axis=1)); gx = np.pad(gx, ((0, 0), (0, 1)))
    gy = np.abs(np.diff(g, axis=0)); gy = np.pad(gy, ((0, 1), (0, 0)))
    mx = int(max_frac * cw); my = int(max_frac * ch)
    sx0, sx1 = ct + int(0.25 * ch), ct + int(0.75 * ch)   # central rows for vertical lines
    sy0, sy1 = cl + int(0.25 * cw), cl + int(0.75 * cw)   # central cols for horizontal lines
    il, cL = inner_line(gx, 'v', cl + 4, cl + mx, sx0, sx1)
    ir, cR = inner_line(gx, 'v', cr - mx, cr - 4, sx0, sx1)
    it, cT = inner_line(gy, 'h', ct + 4, ct + my, sy0, sy1)
    ib, cB = inner_line(gy, 'h', cb - my, cb - 4, sy0, sy1)
    Lb, Rb = il - cl, cr - ir
    Tb, Bb = it - ct, cb - ib
    Lpct = 100 * Lb / max(Lb + Rb, 1)
    Tpct = 100 * Tb / max(Tb + Bb, 1)
    conf = float(min(cL, cR, cT, cB))
    return dict(card=(cl, ct, cr, cb), inner=(il, it, ir, ib),
                Lpct=Lpct, Tpct=Tpct, conf=conf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--maxw", type=int, default=1500, help="downscale long side for speed")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    paths = glob.glob("data/tag_raw/*/metadata.json"); random.Random(3).shuffle(paths)
    rows = []
    for p in paths:
        if len(rows) >= args.n:
            break
        cert = os.path.basename(os.path.dirname(p))
        ip = f"data/tag_raw/{cert}/images/FRONT_MAIN.jpg"
        if not os.path.exists(ip):
            continue
        try:
            meta = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        glr = parse_ratio(meta.get("centering_front_lr")); gtb = parse_ratio(meta.get("centering_front_tb"))
        if not glr or not gtb:
            continue
        im = Image.open(ip).convert("RGB")
        if im.height > args.maxw:
            im = im.resize((int(im.width * args.maxw / im.height), args.maxw))
        a = np.asarray(im, np.float32)
        m = measure(a)
        rows.append((cert, im, m, glr[0], gtb[0]))

    lr_err = [abs(m["Lpct"] - gl) for _, _, m, gl, gt in rows]
    tb_err = [abs(m["Tpct"] - gt) for _, _, m, gl, gt in rows]
    # grade-axis: worst-axis ratio error (what actually matters)
    worst_err = [max(abs(m["Lpct"] - gl), abs(m["Tpct"] - gt)) for _, _, m, gl, gt in rows]

    # grid
    n = len(rows); cols = 4; r = (n + cols - 1) // cols
    fig, axes = plt.subplots(r, cols, figsize=(cols * 3.0, r * 4.0)); axes = np.array(axes).reshape(-1)
    for ax in axes:
        ax.axis("off")
    for i, (cert, im, m, gl, gt) in enumerate(rows):
        ax = axes[i]; ax.imshow(im)
        cl, ct, cr, cb = m["card"]; il, it, ir, ib = m["inner"]
        ax.add_patch(mpatches.Rectangle((cl, ct), cr - cl, cb - ct, fill=False, ec="#34c759", lw=1.2))
        ax.add_patch(mpatches.Rectangle((il, it), ir - il, ib - it, fill=False, ec="#00e5ff", lw=1.4))
        ax.set_title(f"{cert} conf={m['conf']:.2f}\nL/R me {m['Lpct']:.0f} | TAG {gl:.0f} (Δ{abs(m['Lpct']-gl):.0f})\n"
                     f"T/B me {m['Tpct']:.0f} | TAG {gt:.0f} (Δ{abs(m['Tpct']-gt):.0f})", fontsize=7)
    fig.suptitle("Centering prototype: green=card edge, cyan=detected inner frame. vs TAG truth.", fontsize=11)
    fig.tight_layout(); fig.savefig(f"{OUT}/proto_grid.png", dpi=120, bbox_inches="tight")

    print(f"n={len(rows)}")
    print(f"L/R MAE = {np.mean(lr_err):.1f} pp   T/B MAE = {np.mean(tb_err):.1f} pp")
    print(f"WORST-AXIS MAE = {np.mean(worst_err):.1f} pp  (median {np.median(worst_err):.1f})")
    print(f"within 3pp (worst-axis): {np.mean(np.array(worst_err) <= 3) * 100:.0f}%")
    print(f"within 5pp (worst-axis): {np.mean(np.array(worst_err) <= 5) * 100:.0f}%")
    print(f"saved {OUT}/proto_grid.png")


if __name__ == "__main__":
    main()
