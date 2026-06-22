"""ROBUSTNESS diagnostic: characterize MAIN-photo border types over a random card sample.

For each card MAIN image we:
  1. detect_outer_quad + warp to a rectified card (no SFX, flat photo only)
  2. extract the BORDER RING (outer strip) where whitening/dirt live
  3. compute border-type statistics defensible for routing:
       sat_med   : median saturation in ring  (low => grey/dark or washed)
       val_med   : median value
       val_p95   : bright tail (specular highlights raise this)
       sparkle   : density of small bright specular spots (white-top-hat > thr),
                   the FOIL/HOLO false-white signature
       hi_freq   : std of laplacian in ring (texture energy; foil sparkles + holo grain high)
       whiteness_frac_naive : fraction the NAIVE detector (V*(1-S) > 0.55) would flag
                              -> proxy for how badly the naive method FLOODS this border
  4. route to {matte_light, matte_dark, foil_holo} by simple rules, report mix + naive-flood.

Run: ./venv/Scripts/python.exe scripts/diag_border_robustness.py
"""
import os, sys, json, random, csv
import numpy as np
import cv2
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.card_detector import detect_outer_quad, warp_card  # noqa

TAG = os.path.join(os.path.dirname(__file__), "..", "data", "tag_raw")
random.seed(7)

def ring_mask(h, w, frac=0.06):
    rw = max(8, int(frac * min(h, w)))
    m = np.zeros((h, w), bool)
    m[:rw,:]=m[-rw:,:]=m[:,:rw]=m[:,-rw:]=True
    return m, rw

def whiteness(rgb):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    S = hsv[...,1]/255.0; V = hsv[...,2]/255.0
    return V*(1.0-S), S, V

def sparkle_index(gray):
    # white top-hat: small bright spots that survive a morphological opening => specular sparkle
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7))
    th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, k)
    return float((th > 35).mean())  # fraction of pixels that are isolated bright specks

def analyze(rgb):
    h,w = rgb.shape[:2]
    m,rw = ring_mask(h,w)
    white,S,V = whiteness(rgb)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    rS, rV, rwhite = S[m], V[m], white[m]
    lap = cv2.Laplacian(gray, cv2.CV_32F)
    spk = sparkle_index(gray[ :rw*4 ])  # top strip sample for speed
    res = dict(
        sat_med=float(np.median(rS)),
        val_med=float(np.median(rV)),
        val_p95=float(np.percentile(rV,95)),
        sparkle=spk,
        hi_freq=float(lap[m].std()),
        naive_white_frac=float((rwhite > 0.55).mean()),
    )
    return res

def route(r):
    # FOIL/HOLO: lots of specular specks OR high texture energy with bright tail
    if r["sparkle"] > 0.06 or (r["hi_freq"] > 28 and r["val_p95"] > 0.75):
        return "foil_holo"
    # DARK: low value border (dirt has no contrast here)
    if r["val_med"] < 0.33:
        return "matte_dark"
    return "matte_light"

def main():
    certs = [c for c in os.listdir(TAG) if c.startswith(("C","E","G","U","V"))]
    random.shuffle(certs)
    rows=[]; tried=0
    for cert in certs:
        if len(rows) >= 60: break
        for side in ("FRONT","BACK"):
            p = os.path.join(TAG, cert, "images", f"{side}_MAIN.jpg")
            if not os.path.exists(p): continue
            tried += 1
            try:
                img = Image.open(p).convert("RGB")
                npimg = np.array(img)[:,:,::-1]  # BGR for cv2 detector
                quad = detect_outer_quad(npimg)
                if quad is None:
                    continue
                warped = warp_card(npimg, quad)
                rgb = np.array(warped.convert("RGB"))
                r = analyze(rgb)
                r["type"]=route(r); r["cert"]=cert; r["side"]=side
                rows.append(r)
            except Exception as e:
                continue
            break  # one side per card to diversify
    import collections
    cc = collections.Counter(x["type"] for x in rows)
    print(f"analyzed {len(rows)} cards (tried {tried} images)")
    print("TYPE MIX:", dict(cc))
    for t in ("matte_light","matte_dark","foil_holo"):
        sub=[x for x in rows if x["type"]==t]
        if not sub: continue
        nf=np.mean([x["naive_white_frac"] for x in sub])
        spk=np.mean([x["sparkle"] for x in sub])
        print(f"  {t:12s} n={len(sub):2d}  naive_flood_frac={nf:.4f}  mean_sparkle={spk:.4f}  "
              f"val_med={np.mean([x['val_med'] for x in sub]):.2f}")
    out = os.path.join(os.path.dirname(__file__),"..","data","_wseg","my_border_diag.csv")
    with open(out,"w",newline="") as f:
        wtr=csv.DictWriter(f, fieldnames=["cert","side","type","sat_med","val_med","val_p95","sparkle","hi_freq","naive_white_frac"])
        wtr.writeheader()
        for x in rows: wtr.writerow({k:x[k] for k in wtr.fieldnames})
    print("wrote", out)

if __name__=="__main__":
    main()
