"""Save larger context crops (256px) around 12 whitening points so a human can judge:
is whitening AT the point, NEAR it, or absent? Also widen the signal search to a
larger neighborhood to test whether the point is a coarse region tag vs precise loc.
MAIN-only.
"""
import os, json, random
import numpy as np
from PIL import Image
import cv2

os.makedirs(r"D:\CardChecker\store_listing\white_label_audit", exist_ok=True)
random.seed(11)
with open(r"D:\CardChecker\scripts\_white_sample.json") as f:
    pts = json.load(f)
random.shuffle(pts)

def whiteness(rgb):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    return (hsv[...,2]/255.0)*(1.0-hsv[...,1]/255.0)

saved = 0
near_signal = 0; checked = 0
for cert, d, side, dt, x, y, region in pts:
    if saved >= 12: break
    ip = os.path.join(d, "images", "FRONT_MAIN.jpg" if side=="front" else "BACK_MAIN.jpg")
    if not os.path.exists(ip): continue
    im = Image.open(ip).convert("RGB"); W,H = im.size; arr = np.asarray(im)
    px,py = int(x),int(y)
    # 256px context crop centered on point
    h = 128
    x0,x1 = max(0,px-h),min(W,px+h); y0,y1 = max(0,py-h),min(H,py+h)
    crop = arr[y0:y1, x0:x1].copy()
    # draw a marker at the point
    cv2.drawMarker(crop, (px-x0, py-y0), (255,0,0), cv2.MARKER_CROSS, 24, 2)
    Image.fromarray(crop).save(rf"D:\CardChecker\store_listing\white_label_audit\{saved:02d}_{cert}_{side}_{dt.split('/')[-1].strip().replace(' ','')}.jpg")
    # wider signal test: search whiteness in a 200px box for any whitening blob
    wh = whiteness(arr); cm = float(np.median(wh))
    box = wh[y0:y1, x0:x1]
    frac_white = float((box > max(0.33, cm+0.2)).mean())
    checked += 1
    if frac_white > 0.01: near_signal += 1
    saved += 1
print(f"saved {saved} context crops -> store_listing/white_label_audit/")
print(f"crops with ANY whitening blob in 256px context (frac>1%): {near_signal}/{checked}")
