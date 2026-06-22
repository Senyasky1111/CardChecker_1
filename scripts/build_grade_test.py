"""Build a BLIND grade-test set: per-side labeled zone montages (what Claude sees) +
a SEPARATE ground-truth file (TAG grade + per-zone defects) used only at scoring.

Montage = 8 labeled zones per side (4 corners + 4 edges), high-res, bold labels so the
grader can attribute defects to the exact zone. Stratified by TAG grade.
"""
import sys, glob, json, os, random
from pathlib import Path
from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.montage import make_montage   # single source of truth for the montage logic
OUT=Path("runs/grade_test"); RIM=False
WHITE={"CORNER WEAR","EDGE WEAR","SURFACE / PLAY WEAR","PLAY WEAR DEFECT"}

def is_ph(x,y): return abs(x-50)<=2 and abs(y-50)<=2

def zone_of(nx,ny,t):
    t=t.lower()
    if "corner" in t: return ("T" if ny<0.5 else "B")+("L" if nx<0.5 else "R")
    if "edge" in t:
        d={"LEFT":nx,"RIGHT":1-nx,"TOP":ny,"BOTTOM":1-ny}; return min(d,key=d.get)
    # play wear -> nearest corner
    return ("T" if ny<0.5 else "B")+("L" if nx<0.5 else "R")

import argparse
_ap=argparse.ArgumentParser(); _ap.add_argument("--n",type=int,default=20)
_ap.add_argument("--seed",type=int,default=42); _ap.add_argument("--out",default="runs/grade_test")
_ap.add_argument("--rim",action="store_true")
_A=_ap.parse_args()
OUT=Path(_A.out); (OUT/"montage").mkdir(parents=True,exist_ok=True); RIM=_A.rim
random.seed(_A.seed)
paths=glob.glob("data/tag_raw/*/metadata.json"); random.shuffle(paths)
# 4 bands across the REAL graded range; only cards with a genuine TAG grade (not ungraded/0)
bands={"gem":[], "nm":[], "ex":[], "low":[]}   # >=9.5 / 8-9 / 5.5-7.5 / <=5
frac={"gem":0.30,"nm":0.30,"ex":0.25,"low":0.15}
want={b:max(1,round(_A.n*frac[b])) for b in bands}
manifest=[]; gt={}
for p in paths:
    if all(len(bands[b])>=want[b] for b in bands): break
    cert=os.path.basename(os.path.dirname(p))
    try: meta=json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: continue
    g=meta.get("grade"); lab=meta.get("grade_label")
    if g is None or not lab or float(g)<=0: continue   # skip ungraded (grade 0 / no label)
    g=float(g)
    band=("gem" if g>=9.5 else "nm" if g>=8 else "ex" if g>=5.5 else "low")
    if len(bands[band])>=want[band]: continue
    if not (os.path.exists(f"data/tag_raw/{cert}/images/FRONT_MAIN.jpg")): continue
    # build per-side montage + GT zones
    sides={}
    okcard=True
    for side in ("front","back"):
        ip=f"data/tag_raw/{cert}/images/{side.upper()}_MAIN.jpg"
        if not os.path.exists(ip):
            sides[side]=None; continue
        try: img=Image.open(ip).convert("RGB")
        except Exception: okcard=False; break
        W,H=img.size
        mont=make_montage(img,cert,side,rim=RIM)
        mp=OUT/"montage"/f"{cert}_{side}.png"; Image.fromarray(mont).save(mp)
        worn={}
        for d in meta.get("surface_defects") or []:
            if d.get("side","front")!=side or d.get("defect_type","") not in WHITE: continue
            if is_ph(d.get("x",0),d.get("y",0)): continue
            nx,ny=d["x"]/W, d["y"]/H
            if not (0<=nx<=1 and 0<=ny<=1): continue
            z=zone_of(nx,ny,d.get("defect_type",""))
            worn.setdefault(z,[]).append(d.get("defect_type",""))
        sides[side]={"montage":str(mp),"worn_zones":sorted(worn.keys())}
    if not okcard or sides.get("front") is None: continue
    bands[band].append(cert)
    manifest.append({"cert":cert,"band":band,
                     "front_montage":sides["front"]["montage"],
                     "back_montage":sides["back"]["montage"] if sides.get("back") else None})
    gt[cert]={"grade":g,"band":band,
              "front_worn":sides["front"]["worn_zones"],
              "back_worn":sides["back"]["worn_zones"] if sides.get("back") else None}

(OUT/"manifest.json").write_text(json.dumps(manifest,indent=2))
(OUT/"_gt_DO_NOT_READ_until_scoring.json").write_text(json.dumps(gt,indent=2))
print("cards: " + " ".join(f"{b}={len(bands[b])}" for b in bands) + f"  total={len(manifest)}")
print(f"montages -> {OUT}/montage/  ;  GT hidden in _gt_DO_NOT_READ...")
