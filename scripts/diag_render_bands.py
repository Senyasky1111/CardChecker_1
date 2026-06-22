"""Render the border band + sparkle map for a few certs so I can eyeball whether the
'foil_holo' classification is real foil or an artifact (halftone/JPEG)."""
import sys
from pathlib import Path
import numpy as np, cv2
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.card_detector import rectify_for_centering  # noqa

ROOT = Path(__file__).resolve().parents[1]
TAG = ROOT / "data" / "tag_raw"
OUT = ROOT / "data" / "_wseg" / "bands"; OUT.mkdir(parents=True, exist_ok=True)

CASES = [("C1029857","BACK"),("C1064348","BACK"),("C1064348","FRONT"),
         ("C1118975","BACK"),("C1224282","BACK"),("C0470826","BACK")]

for cert, side in CASES:
    p = TAG/cert/"images"/f"{side}_MAIN.jpg"
    if not p.exists(): print("missing",p); continue
    rec = rectify_for_centering(Image.open(p))
    w = np.asarray(rec["warped"].convert("RGB"))
    o = rec["outer"]
    # crop top border strip (a horizontal slab just inside the top edge)
    cw, ch = o["right"]-o["left"], o["bottom"]-o["top"]
    rw = max(6,int(0.05*min(cw,ch)))
    y0 = o["top"]+int(1.5*rw); y1 = y0+3*rw
    x0,x1 = o["left"]+int(0.1*cw), o["left"]+int(0.9*cw)
    strip = w[y0:y1, x0:x1]
    V = cv2.cvtColor(strip, cv2.COLOR_RGB2HSV)[...,2]
    med9 = cv2.medianBlur(V,9)
    spec = ((V.astype(np.int16)-med9.astype(np.int16))>35)&(V>153)
    vis = strip.copy(); vis[spec]=(255,0,255)
    # upscale 3x for clarity
    both = np.vstack([strip, vis])
    both = cv2.resize(both, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
    Image.fromarray(both).save(OUT/f"{cert}_{side}.png")
    print("wrote", OUT/f"{cert}_{side}.png", "spec_px=", int(spec.sum()), "strip=", strip.shape)
