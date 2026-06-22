"""Build an AUTO-CLEANED whitening segmentation dataset from TAG points (MAIN-only).

TAG points are coarse + ~half point at flat-invisible wear. So we DON'T trust every point:
we keep a point ONLY if a real whitening blob is visible near it (TAG-point AND visible-white).
This yields fewer but CLEAN positive masks. Background (orange scan) is excluded via the card
interior mask. Reports the clean-positive YIELD and emits a verification gallery.

Usage: python scripts/build_whitening_dataset.py --max-cards 1500 --out data/whitening_ds
"""
import sys, glob, json, os, random, argparse, math
from pathlib import Path
import numpy as np, cv2
from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.card_detector import detect_outer_quad
WHITE={"CORNER WEAR","EDGE WEAR","SURFACE / PLAY WEAR","PLAY WEAR DEFECT"}

def is_ph(x,y): return abs(x-50)<=2 and abs(y-50)<=2

def card_interior(img):
    q=detect_outer_quad(np.asarray(img)); W,H=img.size
    m=np.zeros((H,W),np.uint8)
    if q is None: m[:]=255; return m
    cv2.fillConvexPoly(m,q.astype(np.int32),255)
    return cv2.erode(m,np.ones((9,9),np.uint8),iterations=2)

def lift(rgb, inter, px, py, win=130, cap_frac=0.16):
    """Return (patch, blob_mask) if a clean whitening blob is found near the point, else None."""
    H,W=rgb.shape[:2]
    x0,y0=max(0,px-win),max(0,py-win); x1,y1=min(W,px+win),min(H,py+win)
    patch=rgb[y0:y1,x0:x1]; ip=inter[y0:y1,x0:x1]>0
    if patch.size==0 or ip.sum()<60: return None
    lab=cv2.cvtColor(patch,cv2.COLOR_RGB2LAB).astype(np.float32)
    L=lab[...,0]; a=lab[...,1]-128; b=lab[...,2]-128
    chroma=np.sqrt(a*a+b*b)
    base_c=np.median(chroma[ip]); base_L=np.median(L[ip])
    # middle-ground: desaturated relative to border AND lighter (white cardstock), inside card
    white=(chroma<base_c*0.62)&(L>base_L+5)&ip
    m=cv2.morphologyEx(white.astype(np.uint8),cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    m=cv2.morphologyEx(m,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    n,lab2,st,cen=cv2.connectedComponentsWithStats(m,8)
    if n<=1: return None
    cx,cy=px-x0,py-y0; best=-1; bd=1e9
    for i in range(1,n):
        if st[i,cv2.CC_STAT_AREA]<10: continue
        d=(cen[i][0]-cx)**2+(cen[i][1]-cy)**2
        if d<bd and d< (win*0.85)**2: bd=d; best=i      # blob must be near the point
    if best<0: return None
    blob=(lab2==best).astype(np.uint8)
    if not (10 <= blob.sum() <= cap_frac*ip.sum()): return None
    return patch.copy(), blob, (cx,cy)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--max-cards",type=int,default=1500)
    ap.add_argument("--out",type=Path,default=Path("data/whitening_ds"))
    args=ap.parse_args(); random.seed(0)
    (args.out/"img").mkdir(parents=True,exist_ok=True); (args.out/"mask").mkdir(parents=True,exist_ok=True)
    paths=glob.glob("data/tag_raw/*/metadata.json"); random.shuffle(paths)
    tried=kept=cards=0; gallery=[]
    for p in paths:
        if cards>=args.max_cards: break
        cert=os.path.basename(os.path.dirname(p))
        try: meta=json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception: continue
        used=False
        for side in ("front","back"):
            pts=[d for d in (meta.get("surface_defects") or [])
                 if d.get("defect_type","") in WHITE and d.get("side","front")==side and not is_ph(d.get("x",0),d.get("y",0))]
            if not pts: continue
            ip_=f"data/tag_raw/{cert}/images/{side.upper()}_MAIN.jpg"
            if not os.path.exists(ip_): continue
            try: img=Image.open(ip_).convert("RGB")
            except Exception: continue
            rgb=np.asarray(img); inter=card_interior(img); W,H=img.size; used=True
            for j,d in enumerate(pts):
                px=min(max(int(d["x"]),0),W-1); py=min(max(int(d["y"]),0),H-1)
                tried+=1; r=lift(rgb,inter,px,py)
                if r is None: continue
                patch,blob,(cx,cy)=r; kept+=1
                name=f"{cert}_{side}_{j}"
                Image.fromarray(patch).save(args.out/"img"/f"{name}.png")
                Image.fromarray(blob*255).save(args.out/"mask"/f"{name}.png")
                if len(gallery)<24:
                    ov=patch.copy(); ov[blob>0]=(0.15*ov[blob>0]+0.85*np.array([255,30,30])).astype(np.uint8)
                    def big(a): return cv2.resize(a,(240,240),interpolation=cv2.INTER_NEAREST)
                    lb=np.full((20,240*2+5,3),255,np.uint8)
                    cv2.putText(lb,f"{cert[:8]} {side} {d.get('defect_type','')[:10]}",(3,14),cv2.FONT_HERSHEY_SIMPLEX,0.4,(0,0,0),1)
                    gallery.append(np.vstack([lb,np.hstack([big(patch),np.full((240,5,3),255,np.uint8),big(ov)])]))
        if used: cards+=1
    if gallery:
        cols=4; rows=math.ceil(len(gallery)/cols); ch=gallery[0].shape[0]; cw=gallery[0].shape[1]
        grid=np.full((rows*(ch+6),cols*(cw+6),3),235,np.uint8)
        for i,t in enumerate(gallery):
            r,c=divmod(i,cols); grid[r*(ch+6):r*(ch+6)+ch,c*(cw+6):c*(cw+6)+cw]=t
        Image.fromarray(grid).save(args.out/"verify_gallery.png")
    print(f"cards={cards}  points_tried={tried}  clean_positives_kept={kept}  yield={100*kept/max(tried,1):.1f}%")
    print(f"-> {args.out}/img, {args.out}/mask ; gallery {args.out}/verify_gallery.png")

if __name__=="__main__": main()
