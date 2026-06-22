"""
Quantitative eval of the rim dot-segmentation prototype.

Two questions:
  Q1 (separation): does total rim white+black blob count separate worn cards (low grade /
     low corner+edge subscore) from gem-mint cards? -> if yes, the signal is real & graded.
  Q2 (localization hit-rate): of TAG CORNER/EDGE WEAR points that land on the rim band,
     how many have a detected blob within tolerance? + false-positive behavior on gems.

Samples ~N cards that HAVE FRONT_MAIN, stratified by grade.
"""
import json, os, sys, glob, random
import numpy as np
import cv2
from PIL import Image

sys.path.insert(0, os.path.abspath("."))
from scripts.seg_dot_prototype import (load_quad_and_warp, map_points, segment_dots,
                                       near_border, RW, RH, RIM_FRAC, HIT_TOL_FRAC)

ROOT = "data/tag_raw"


def collect(n_per_bin=18):
    dirs = sorted(glob.glob(ROOT + "/C*"))
    bins = {"low": [], "mid": [], "gem": []}
    random.seed(1)
    random.shuffle(dirs)
    for d in dirs:
        if not os.path.exists(os.path.join(d, "images", "FRONT_MAIN.jpg")):
            continue
        try:
            m = json.load(open(os.path.join(d, "metadata.json")))
        except Exception:
            continue
        g = m.get("grade")
        if g is None:
            continue
        if g <= 4 and len(bins["low"]) < n_per_bin:
            bins["low"].append(os.path.basename(d))
        elif 5 <= g <= 7 and len(bins["mid"]) < n_per_bin:
            bins["mid"].append(os.path.basename(d))
        elif g >= 9.5 and len(bins["gem"]) < n_per_bin:
            bins["gem"].append(os.path.basename(d))
        if all(len(v) >= n_per_bin for v in bins.values()):
            break
    return bins


def eval_card(cert):
    warped, M, method = load_quad_and_warp(cert, "front")
    if warped is None:
        return None
    rim_px = int(RIM_FRAC * RW)
    blobs, _, _ = segment_dots(warped, rim_px)
    allb = [(*b, "w") for b in blobs["white"]] + [(*b, "k") for b in blobs["black"]]
    allb = [b for b in allb if near_border(b[0], b[1], RW, RH, rim_px)]
    m = json.load(open(os.path.join(ROOT, cert, "metadata.json")))
    wear = [d for d in (m.get("surface_defects") or [])
            if d.get("side") == "front" and "WEAR" in d.get("defect_type", "").upper()
            and not (d.get("x", 0) < 120 and d.get("y", 0) < 120)]
    xy = map_points([(d["x"], d["y"]) for d in wear], M)
    tol = HIT_TOL_FRAC * RW
    tag_border = 0; hits = 0
    for (tx, ty) in xy:
        if not near_border(tx, ty, RW, RH, rim_px):
            continue
        tag_border += 1
        dmin = min([np.hypot(bx-tx, by-ty) for (bx, by, *_ ) in allb], default=1e9)
        if dmin <= tol:
            hits += 1
    return {
        "cert": cert, "grade": m.get("grade"),
        "corners_f": m.get("corners_front"), "edges_f": m.get("edges_front"),
        "nblob": len(allb), "nwhite": len(blobs["white"]), "nblack": len(blobs["black"]),
        "tag_border": tag_border, "hits": hits,
    }


def main():
    bins = collect()
    print("sample sizes:", {k: len(v) for k, v in bins.items()})
    res = {k: [] for k in bins}
    for k, certs in bins.items():
        for c in certs:
            r = eval_card(c)
            if r:
                res[k].append(r)

    print("\n=== Q1: rim blob count vs grade bin ===")
    print(f"{'bin':5} {'n':3} {'mean_blob':9} {'median':7} {'mean_white':10} {'mean_black':10}")
    for k in ("low", "mid", "gem"):
        rs = res[k]
        if not rs: continue
        nb = [r["nblob"] for r in rs]
        nw = [r["nwhite"] for r in rs]; nk = [r["nblack"] for r in rs]
        print(f"{k:5} {len(rs):3} {np.mean(nb):9.1f} {np.median(nb):7.0f} {np.mean(nw):10.1f} {np.mean(nk):10.1f}")

    print("\n=== Q2: TAG wear hit-rate (border points only) ===")
    tot_border = tot_hits = 0
    for k in ("low", "mid"):
        for r in res[k]:
            tot_border += r["tag_border"]; tot_hits += r["hits"]
    print(f"border wear points: {tot_border}, hits within tol: {tot_hits}, "
          f"recall={100*tot_hits/max(tot_border,1):.0f}%")

    # FP proxy on gems: blobs per gem card (should be low if specks==wear)
    gem_blobs = [r["nblob"] for r in res["gem"]]
    low_blobs = [r["nblob"] for r in res["low"]]
    print(f"\nGEM mean blobs/card: {np.mean(gem_blobs):.1f}  (these are FALSE positives — gems have no wear)")
    print(f"LOW  mean blobs/card: {np.mean(low_blobs):.1f}")
    print(f"separation ratio low/gem: {np.mean(low_blobs)/max(np.mean(gem_blobs),1e-6):.2f}x")

    # threshold sweep: classify worn (low) vs gem by blob count
    import numpy as np2
    y = [1]*len(low_blobs) + [0]*len(gem_blobs)
    x = low_blobs + gem_blobs
    best = (0, 0)
    for t in range(0, 40):
        pred = [1 if v > t else 0 for v in x]
        tp = sum(1 for p, yy in zip(pred, y) if p == 1 and yy == 1)
        fp = sum(1 for p, yy in zip(pred, y) if p == 1 and yy == 0)
        tn = sum(1 for p, yy in zip(pred, y) if p == 0 and yy == 0)
        fn = sum(1 for p, yy in zip(pred, y) if p == 0 and yy == 1)
        acc = (tp+tn)/len(y)
        if acc > best[1]:
            best = (t, acc, tp, fp, tn, fn)
    print(f"\nbest blob-count threshold low-vs-gem: >{best[0]} blobs -> acc={best[1]:.2f} "
          f"(tp={best[2]} fp={best[3]} tn={best[4]} fn={best[5]})")


if __name__ == "__main__":
    main()
