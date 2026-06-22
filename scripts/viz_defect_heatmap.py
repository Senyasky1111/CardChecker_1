"""Visualize what the trained defect-heatmap model actually produces.

Two modes:
  tiles : grid of N val tiles -> predicted per-class heatmap glow + model peaks
          vs the TAG ground-truth point. Fast sanity of localization quality.
  card  : full native-res card -> sliding-window 512px tiles, stitch the stride-4
          heatmaps into a card-level glow, extract peaks, overlay vs ALL TAG points
          from the card metadata. This is the real product view.

CPU is fine (a few tiles). Loads models/defect_heatmap_best.pt (HRNet, ep11).

Usage:
  ./venv/Scripts/python.exe scripts/viz_defect_heatmap.py --mode tiles --n 12
  ./venv/Scripts/python.exe scripts/viz_defect_heatmap.py --mode card --n 3
"""
from __future__ import annotations
import argparse, json, random, sys
from pathlib import Path
from collections import defaultdict

import numpy as np
import torch
from PIL import Image
import torchvision.transforms as T
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

sys.path.insert(0, str(Path(__file__).parent))
from train_defect_heatmap import HeatmapNet, extract_peaks, CLASSES, NC  # noqa

ROOT = Path("d:/CardChecker")
TILES = ROOT / "data/tag_v3_tiles"
RAW = ROOT / "data/tag_raw"
OUT = ROOT / "runs/defect_full/viz"
CKPT = ROOT / "models/defect_heatmap_best.pt"
TAG_W, TAG_H = 4463, 6161
PLACEHOLDER = {(0, 0), (50, 50)}

# distinct color per class for peak/point markers
CLS_COLORS = ["#ff3b30", "#ff9500", "#ffcc00", "#34c759",
              "#00c7be", "#007aff", "#af52de"]

_NORM = T.Compose([T.ToTensor(),
                   T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])])


def load_model():
    import pathlib
    _posix = pathlib.PosixPath
    pathlib.PosixPath = pathlib.WindowsPath  # ckpt 'args' has a Linux PosixPath
    try:
        ckpt = torch.load(CKPT, map_location="cpu", weights_only=False)
    finally:
        pathlib.PosixPath = _posix
    backbone = ckpt.get("args", {}).get("backbone", "hrnet_w32")
    m = HeatmapNet(backbone, pretrained=False)
    m.load_state_dict(ckpt["model"])
    m.eval()
    print(f"loaded {CKPT.name} (backbone={backbone})")
    return m


@torch.no_grad()
def infer_tile(model, pil_img):
    """pil 512x512 -> sigmoid heatmap (NC, 128, 128) as float numpy."""
    x = _NORM(pil_img).unsqueeze(0)
    hm = torch.sigmoid(model(x).float())[0]
    return hm.numpy()


def glow_from_hm(hm_np):
    """(NC,h,w) -> (h,w) intensity (max over classes) + (h,w) argmax class."""
    inten = hm_np.max(0)
    cls = hm_np.argmax(0)
    return inten, cls


# --------------------------------------------------------------------------- tiles

def run_tiles(model, n, thr):
    lbl_dir = TILES / "labels/val"
    img_dir = TILES / "images/val"
    items = []
    for lp in lbl_dir.glob("*.txt"):
        parts = lp.read_text().split()
        if len(parts) != 3:
            continue
        cls, txn, tyn = int(parts[0]), float(parts[1]), float(parts[2])
        ip = img_dir / f"{lp.stem}.jpg"
        if ip.exists():
            items.append((ip, cls, txn, tyn))
    random.Random(0).shuffle(items)
    # try to cover variety of classes
    bycls = defaultdict(list)
    for it in items:
        bycls[it[1]].append(it)
    chosen = []
    ci = 0
    while len(chosen) < n and any(bycls.values()):
        c = ci % NC
        if bycls[c]:
            chosen.append(bycls[c].pop())
        ci += 1
    chosen = chosen[:n]

    cols = 4
    rows = (len(chosen) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 3.4, rows * 3.4))
    axes = np.array(axes).reshape(-1)
    for ax in axes:
        ax.axis("off")
    for k, (ip, cls, txn, tyn) in enumerate(chosen):
        img = Image.open(ip).convert("RGB")
        tile = 512
        img512 = img.resize((tile, tile)) if img.size != (tile, tile) else img
        hm = infer_tile(model, img512)
        inten, clsmap = glow_from_hm(hm)
        inten_up = np.array(Image.fromarray((inten * 255).astype(np.uint8)).resize((tile, tile))) / 255.0
        ax = axes[k]
        ax.imshow(img512)
        ax.imshow(inten_up, cmap="inferno", alpha=(inten_up > thr) * 0.55)
        # GT point (white ring)
        ax.add_patch(mpatches.Circle((txn * tile, tyn * tile), 18, fill=False,
                                     ec="white", lw=2.0))
        # model peaks
        peaks = extract_peaks(torch.from_numpy(hm), thr=thr)
        for pc, py, px, sc in peaks:
            ax.add_patch(mpatches.Circle((px / hm.shape[1] * tile, py / hm.shape[1] * tile),
                                         10, fill=False, ec=CLS_COLORS[pc], lw=2.0))
        ax.set_title(f"GT={CLASSES[cls]}  | peaks={len(peaks)}", fontsize=8)
        ax.axis("off")
    fig.suptitle("Defect model on val tiles — white ring = TAG GT point, colored = model peaks",
                 fontsize=11)
    fig.tight_layout()
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "tiles_grid.png"
    fig.savefig(p, dpi=110, bbox_inches="tight")
    print(f"saved {p}")


# --------------------------------------------------------------------------- card

def tag_points(cert, side):
    mp = RAW / cert / "metadata.json"
    if not mp.exists():
        return []
    meta = json.loads(mp.read_text(encoding="utf-8"))
    pts = []
    for d in meta.get("surface_defects") or []:
        if d.get("side", "front") != side:
            continue
        if (d.get("x"), d.get("y")) in PLACEHOLDER:
            continue
        pts.append((d.get("x"), d.get("y"), d.get("defect_type", "")))
    return pts


@torch.no_grad()
def run_card(model, cert, side, thr, tile=512, stride=384, batch=8):
    ip = RAW / cert / "images" / f"{side.upper()}_MAIN.jpg"
    if not ip.exists():
        print(f"  no image {ip}")
        return False
    im = Image.open(ip).convert("RGB")
    W, H = im.size
    s = tile // 4  # stride-4 heatmap tile size = 128
    accW, accH = W // 4, H // 4
    acc = np.zeros((NC, accH, accW), dtype=np.float32)

    xs = list(range(0, max(1, W - tile + 1), stride)) + [W - tile]
    ys = list(range(0, max(1, H - tile + 1), stride)) + [H - tile]
    xs = sorted(set(max(0, x) for x in xs))
    ys = sorted(set(max(0, y) for y in ys))
    coords = [(x, y) for y in ys for x in xs]
    print(f"  {cert} {side}: {W}x{H}, {len(coords)} tiles")

    buf, off = [], []
    def flush():
        if not buf:
            return
        x = torch.stack(buf)
        hm = torch.sigmoid(model(x).float()).numpy()  # (b,NC,128,128)
        for j, (ox, oy) in enumerate(off):
            ay, ax_ = oy // 4, ox // 4
            h, w = hm.shape[2], hm.shape[3]
            sl = acc[:, ay:ay + h, ax_:ax_ + w]
            np.maximum(sl, hm[j, :, :sl.shape[1], :sl.shape[2]], out=sl)
        buf.clear(); off.clear()

    for (x0, y0) in coords:
        crop = im.crop((x0, y0, x0 + tile, y0 + tile))
        buf.append(_NORM(crop)); off.append((x0, y0))
        if len(buf) >= batch:
            flush()
    flush()

    inten = acc.max(0)
    peaks = extract_peaks(torch.from_numpy(acc), thr=thr)
    gts = tag_points(cert, side)

    disp = im.resize((accW, accH))
    fig, ax = plt.subplots(figsize=(accW / 110, accH / 110))
    ax.imshow(disp)
    ax.imshow(inten, cmap="inferno", alpha=(inten > thr) * 0.55)
    for x, y, dt in gts:  # TAG GT points (scaled to /4 display)
        ax.add_patch(mpatches.Circle((x / TAG_W * accW, y / TAG_H * accH), 26,
                                     fill=False, ec="white", lw=1.8))
    for pc, py, px, sc in peaks:  # model peaks (acc coords already /4)
        ax.add_patch(mpatches.Circle((px, py), 14, fill=False, ec=CLS_COLORS[pc], lw=1.8))
    ax.set_title(f"{cert} {side} — white=TAG ({len(gts)}), colored=model peaks ({len(peaks)})",
                 fontsize=9)
    ax.axis("off")
    handles = [mpatches.Patch(color=CLS_COLORS[c], label=CLASSES[c]) for c in range(NC)]
    ax.legend(handles=handles, fontsize=6, loc="lower right", framealpha=0.8)
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"card_{cert}_{side}.png"
    fig.savefig(p, dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved {p}  (TAG pts={len(gts)}, model peaks={len(peaks)})")
    return True


def pick_card_certs(n, rank="defects"):
    """Pick val certs present in tag_raw. rank='defects' -> most defect tiles first
    (cards with real damage = something to find); rank='random' -> shuffled."""
    cnt = defaultdict(lambda: defaultdict(int))  # cert -> side -> #tiles
    for lp in (TILES / "labels/val").glob("*.txt"):
        parts = lp.stem.rsplit("_", 2)
        if len(parts) != 3:
            continue
        cert, side, _ = parts
        cnt[cert][side] += 1
    cands = []
    for cert, sides in cnt.items():
        side = max(sides, key=sides.get)        # side with most defects
        total = sum(sides.values())
        if (RAW / cert / "images" / f"{side.upper()}_MAIN.jpg").exists():
            cands.append((cert, side, total))
    if rank == "defects":
        cands.sort(key=lambda t: -t[2])
    else:
        random.Random(1).shuffle(cands)
    return [(c, s) for c, s, _ in cands[:n]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["tiles", "card", "both"], default="both")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--thr", type=float, default=0.2)
    ap.add_argument("--cert", default=None, help="specific cert for card mode")
    ap.add_argument("--side", default="front")
    args = ap.parse_args()

    model = load_model()
    if args.mode in ("tiles", "both"):
        run_tiles(model, args.n, args.thr)
    if args.mode in ("card", "both"):
        if args.cert:
            run_card(model, args.cert, args.side, args.thr)
        else:
            for cert, side in pick_card_certs(3):
                run_card(model, cert, side, args.thr)


if __name__ == "__main__":
    main()
