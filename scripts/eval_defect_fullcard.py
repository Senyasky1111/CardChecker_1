"""EXP-0: honest FULL-CARD evaluation of the defect heatmap model.

Why: the in-training metric (eval_pointF1) is structurally blind to the full-card flood
(it scores only defect-centered tiles and counts FP only in the miss branch). This harness
measures the thing the product actually needs, on whole cards, with a threshold sweep:

  * RECALL  — fraction of ALL TAG points on DEFECTED cards that get a model peak within r.
              (TAG labels are CAPPED/non-exhaustive, so unmatched peaks on defected cards are
               NOT necessarily false positives -> we do NOT call them FP. Recall only here.)
  * FP/CARD — number of model peaks on CLEAN (gem-mint, 0-defect) cards = true false alarms.

Operating point = max recall subject to FP/clean-card <= 0.5 (the spec ship gate).
Also: a cheap visibility proxy (local gradient energy at each TAG point vs background) to
estimate what fraction of annotated defects carry any flat-light signal at all.

Leakage: DEFECTED cards are drawn from the val/test split only (model trained on train tiles).
CLEAN cards have no defect points -> never in defect training.

Usage:
  ./venv/Scripts/python.exe scripts/eval_defect_fullcard.py --n-def 30 --n-clean 30
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
from collections import defaultdict

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent))
from train_defect_heatmap import HeatmapNet, NC  # noqa

ROOT = Path("d:/CardChecker")
RAW = ROOT / "data/tag_raw"
V3 = ROOT / "data/tag_v3/detection"   # split assignment
CKPT = ROOT / "models/defect_heatmap_best.pt"
OUT = ROOT / "runs/defect_full/exp0_eval"
TAG_W, TAG_H = 4463, 6161
PLACEHOLDER = {(0, 0), (50, 50)}
import torchvision.transforms as T
_NORM = T.Compose([T.ToTensor(),
                   T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])])
THRS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


def load_model():
    import pathlib
    _p = pathlib.PosixPath
    pathlib.PosixPath = pathlib.WindowsPath
    try:
        ckpt = torch.load(CKPT, map_location="cpu", weights_only=False)
    finally:
        pathlib.PosixPath = _p
    m = HeatmapNet(ckpt.get("args", {}).get("backbone", "hrnet_w32"), pretrained=False)
    m.load_state_dict(ckpt["model"]); m.eval()
    return m


def split_map():
    """cert -> split, from the existing tag_v3 detection split (train/val/test)."""
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


def card_defects(cert, side):
    mp = RAW / cert / "metadata.json"
    if not mp.exists():
        return None, []
    meta = json.loads(mp.read_text(encoding="utf-8"))
    pts = []
    for d in meta.get("surface_defects") or []:
        if d.get("side", "front") != side:
            continue
        if (d.get("x"), d.get("y")) in PLACEHOLDER:
            continue
        pts.append((d["x"], d["y"]))
    return meta, pts


@torch.no_grad()
def infer_acc(model, im, tile=512, stride=448, batch=16):
    """Sliding-window -> per-class stride-4 heatmap accumulator (NC, H/4, W/4), max-blended."""
    W, H = im.size
    accW, accH = W // 4, H // 4
    acc = np.zeros((NC, accH, accW), dtype=np.float32)
    xs = sorted(set([x for x in range(0, max(1, W - tile + 1), stride)] + [W - tile]))
    ys = sorted(set([y for y in range(0, max(1, H - tile + 1), stride)] + [H - tile]))
    coords = [(max(0, x), max(0, y)) for y in ys for x in xs]
    buf, off = [], []

    def flush():
        if not buf:
            return
        hm = torch.sigmoid(model(torch.stack(buf)).float()).numpy()
        for j, (ox, oy) in enumerate(off):
            ay, ax = oy // 4, ox // 4
            sl = acc[:, ay:ay + hm.shape[2], ax:ax + hm.shape[3]]
            np.maximum(sl, hm[j, :, :sl.shape[1], :sl.shape[2]], out=sl)
        buf.clear(); off.clear()

    for (x0, y0) in coords:
        buf.append(_NORM(im.crop((x0, y0, x0 + tile, y0 + tile))))
        off.append((x0, y0))
        if len(buf) >= batch:
            flush()
    flush()
    return acc, accW, accH


def agnostic_peaks(acc, thr, nms_k=7):
    """class-agnostic peaks on max-over-class map. Return list of (ay,ax,score)."""
    m = torch.from_numpy(acc.max(0))[None, None]
    pooled = F.max_pool2d(m, nms_k, stride=1, padding=nms_k // 2)[0, 0]
    mm = m[0, 0]
    keep = (mm == pooled) & (mm > thr)
    idx = keep.nonzero(as_tuple=False)
    return [(int(y), int(x), float(mm[y, x])) for y, x in idx.tolist()]


def grad_energy(im_gray, px, py, win=48):
    """local gradient magnitude mean in a window around (px,py) — visibility proxy."""
    H, W = im_gray.shape
    x0, x1 = max(0, px - win), min(W, px + win)
    y0, y1 = max(0, py - win), min(H, py + win)
    patch = im_gray[y0:y1, x0:x1].astype(np.float32)
    if patch.size < 16:
        return 0.0
    gy, gx = np.gradient(patch)
    return float(np.mean(np.hypot(gx, gy)))


def pick_defected(sm, n, min_pts=8):
    """First n val/test cards with >= min_pts defect points (representative, not cherry-picked)."""
    out = []
    for cert, sp in sm.items():
        if sp == "train":
            continue
        for side in ("front", "back"):
            if not (RAW / cert / "images" / f"{side.upper()}_MAIN.jpg").exists():
                continue
            _, pts = card_defects(cert, side)
            if len(pts) >= min_pts:
                out.append((cert, side, len(pts)))
                break
        if len(out) >= n:
            break
    return out


def pick_clean(n, min_grade=9.5):
    """gem-mint cards with 0 defects -> true negatives for FP measurement."""
    out = []
    for mp in RAW.glob("*/metadata.json"):
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        g = meta.get("grade") or 0
        sd = meta.get("surface_defects") or []
        real_sd = [d for d in sd if (d.get("x"), d.get("y")) not in PLACEHOLDER]
        if g >= min_grade and len(real_sd) == 0:
            cert = mp.parent.name
            for side in ("front", "back"):
                if (RAW / cert / "images" / f"{side.upper()}_MAIN.jpg").exists():
                    out.append((cert, side, g))
                    break
        if len(out) >= n:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-def", type=int, default=30)
    ap.add_argument("--n-clean", type=int, default=30)
    ap.add_argument("--min-pts", type=int, default=8)
    ap.add_argument("--match-r", type=int, default=6, help="match radius in acc-px (=4x card px); 6=24px")
    ap.add_argument("--nms-k", type=int, default=7)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    model = load_model()
    sm = split_map()
    print(f"split: {sum(v=='train' for v in sm.values())} train / "
          f"{sum(v=='val' for v in sm.values())} val / {sum(v=='test' for v in sm.values())} test")

    defected = pick_defected(sm, args.n_def, args.min_pts)
    clean = pick_clean(args.n_clean)
    print(f"defected cards: {len(defected)} (>= {args.min_pts} pts)  |  clean cards: {len(clean)}")

    # --- defected: recall sweep + visibility ---
    recall_hits = {t: 0 for t in THRS}
    total_pts = 0
    vis_point = defaultdict(list)
    vis_bg = []
    rng = np.random.RandomState(0)
    for i, (cert, side, npts) in enumerate(defected):
        im = Image.open(RAW / cert / "images" / f"{side.upper()}_MAIN.jpg").convert("RGB")
        W, H = im.size
        acc, accW, accH = infer_acc(model, im)
        _, pts = card_defects(cert, side)
        # to acc coords
        apts = [(int(y / TAG_H * accH), int(x / TAG_W * accW)) for (x, y) in pts]
        total_pts += len(apts)
        for t in THRS:
            pk = agnostic_peaks(acc, t, args.nms_k)
            for (ay, ax) in apts:
                if any((py - ay) ** 2 + (px - ax) ** 2 <= args.match_r ** 2 for (py, px, _) in pk):
                    recall_hits[t] += 1
        # visibility proxy
        gray = np.asarray(im.convert("L"))
        for (x, y) in pts:
            vis_point[_pt_class_unknown()].append(grad_energy(gray, x, y))
        for _ in range(len(pts)):
            rx, ry = rng.randint(200, W - 200), rng.randint(200, H - 200)
            vis_bg.append(grad_energy(gray, rx, ry))
        print(f"  [def {i+1}/{len(defected)}] {cert} {side} pts={len(pts)}", flush=True)

    # --- clean: FP sweep ---
    fp_counts = {t: 0 for t in THRS}
    for i, (cert, side, g) in enumerate(clean):
        im = Image.open(RAW / cert / "images" / f"{side.upper()}_MAIN.jpg").convert("RGB")
        acc, accW, accH = infer_acc(model, im)
        for t in THRS:
            fp_counts[t] += len(agnostic_peaks(acc, t, args.nms_k))
        print(f"  [clean {i+1}/{len(clean)}] {cert} {side} grade={g}", flush=True)

    recall = {t: (recall_hits[t] / total_pts if total_pts else 0) for t in THRS}
    fp_card = {t: (fp_counts[t] / max(len(clean), 1)) for t in THRS}

    # operating point: max recall with fp/card <= 0.5
    ok = [t for t in THRS if fp_card[t] <= 0.5]
    op = max(ok, key=lambda t: recall[t]) if ok else None

    vp = np.array([v for vs in vis_point.values() for v in vs])
    vb = np.array(vis_bg)
    vis_ratio = float(np.median(vp) / max(np.median(vb), 1e-6)) if len(vp) and len(vb) else None
    frac_lowsignal = float(np.mean(vp <= np.median(vb))) if len(vp) and len(vb) else None

    result = {
        "n_def": len(defected), "n_clean": len(clean), "total_tag_pts": total_pts,
        "match_r_accpx": args.match_r, "nms_k": args.nms_k,
        "recall_by_thr": recall, "fp_per_clean_card_by_thr": fp_card,
        "operating_point": {"thr": op, "recall": recall.get(op), "fp_per_card": fp_card.get(op)} if op else None,
        "visibility": {"median_point/median_bg_grad_ratio": vis_ratio,
                       "frac_points_below_bg_median": frac_lowsignal},
    }
    (OUT / "exp0_result.json").write_text(json.dumps(result, indent=2))

    # plot recall vs fp/card
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.plot([fp_card[t] for t in THRS], [recall[t] for t in THRS], "-o")
    for t in THRS:
        ax.annotate(f"{t}", (fp_card[t], recall[t]), fontsize=7)
    ax.axvline(0.5, color="r", ls="--", lw=1, label="FP=0.5/card gate")
    ax.set_xlabel("false peaks per CLEAN card"); ax.set_ylabel("recall on TAG points (defected cards)")
    ax.set_title("EXP-0 full-card operating curve (thr labeled)")
    ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(OUT / "exp0_curve.png", dpi=120)

    print("\n=== EXP-0 RESULT ===")
    print(f"{'thr':>5}{'recall':>9}{'FP/clean-card':>15}")
    for t in THRS:
        print(f"{t:>5}{recall[t]:>9.3f}{fp_card[t]:>15.2f}")
    print(f"\noperating point (FP<=0.5): {result['operating_point']}")
    print(f"visibility: point/bg grad ratio={vis_ratio}, "
          f"frac points below bg-median={frac_lowsignal}")
    print(f"saved {OUT/'exp0_result.json'} + exp0_curve.png")


def _pt_class_unknown():
    return "all"


if __name__ == "__main__":
    main()
