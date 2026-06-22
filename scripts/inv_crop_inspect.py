"""Sample ~30 whitening points, crop the MAIN image region around each, and report
whether the label is localizable: image dims, normalized coords, where the point sits
(border ring? corner? interior?), and brightness/saturation stats of a patch around it
vs the card median -- a proxy for 'is there a visible whitening signal at this point'.

MAIN-only. Also checks how many sampled cards actually have FRONT_MAIN/BACK_MAIN on disk.
"""
from __future__ import annotations
import os, json, random
import numpy as np
from PIL import Image
import cv2

random.seed(7)
with open(r"D:\CardChecker\scripts\_white_sample.json") as f:
    pts = json.load(f)

random.shuffle(pts)

def whiteness(rgb):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    S = hsv[..., 1] / 255.0; V = hsv[..., 2] / 255.0
    return V * (1.0 - S)

n_have_main = 0
n_checked = 0
n_in_border = 0
n_signal = 0
rows = []
for cert, d, side, dt, x, y, region in pts:
    if n_checked >= 30:
        break
    img_name = "FRONT_MAIN.jpg" if side == "front" else "BACK_MAIN.jpg"
    ip = os.path.join(d, "images", img_name)
    if not os.path.exists(ip):
        continue
    n_have_main += 1
    try:
        im = Image.open(ip).convert("RGB")
    except Exception:
        continue
    W, H = im.size
    arr = np.asarray(im)
    n_checked += 1
    nx, ny = x / W, y / H
    # distance to nearest edge as fraction of dim (border-ring proxy)
    edge_frac = min(nx, 1 - nx, ny, 1 - ny)
    in_border = edge_frac < 0.10
    if in_border:
        n_in_border += 1
    # patch around point
    px, py = int(x), int(y)
    r = max(12, int(0.012 * max(W, H)))  # ~1.2% of long side
    x0, x1 = max(0, px - r), min(W, px + r)
    y0, y1 = max(0, py - r), min(H, py + r)
    patch = arr[y0:y1, x0:x1]
    wh = whiteness(arr)
    patch_wh = wh[y0:y1, x0:x1]
    card_med = float(np.median(wh))
    patch_p90 = float(np.percentile(patch_wh, 90)) if patch_wh.size else 0.0
    signal = patch_p90 - card_med  # how much whiter the brightest part of the patch is vs card
    has_sig = signal > 0.12
    if has_sig:
        n_signal += 1
    rows.append((cert, side, dt, region, W, H, round(nx, 3), round(ny, 3),
                 round(edge_frac, 3), in_border, round(card_med, 3),
                 round(patch_p90, 3), round(signal, 3), has_sig))

print(f"sampled (have MAIN on disk): {n_checked}")
print(f"{'cert':9s} {'side':5s} {'type':12s} {'reg':3s} {'WxH':11s} {'nx':5s} {'ny':5s} {'edgef':5s} {'bord':4s} {'cmed':5s} {'p90':5s} {'sig':6s} {'visible'}")
for (cert, side, dt, region, W, H, nx, ny, ef, ib, cm, p90, sig, hs) in rows:
    dts = dt[:12]
    print(f"{cert:9s} {side:5s} {dts:12s} {str(region):3s} {W}x{H:<6} {nx:<5} {ny:<5} {ef:<5} {str(ib):4s} {cm:<5} {p90:<5} {sig:<6} {hs}")

print()
print(f"in border ring (edge_frac<0.10): {n_in_border}/{n_checked}")
print(f"patch shows whitening signal (p90-cardmed>0.12): {n_signal}/{n_checked}")

# also: how many of the 400 sampled cards have MAIN on disk (disk coverage proxy)
have = 0; tot = 0
seen = set()
for cert, d, side, dt, x, y, region in pts:
    key = (cert, side)
    if key in seen: continue
    seen.add(key)
    tot += 1
    img_name = "FRONT_MAIN.jpg" if side == "front" else "BACK_MAIN.jpg"
    if os.path.exists(os.path.join(d, "images", img_name)):
        have += 1
    if tot >= 400: break
print(f"\nMAIN-on-disk coverage over {tot} sampled (cert,side): {have} ({100*have/max(1,tot):.1f}%)")
