"""One card per TAG grade 1..10 -> base montages + full cards + GT, for a showcase report."""
import sys, glob, json, os, random
from pathlib import Path
import numpy as np, cv2
from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
OUT=Path("runs/grade_showcase"); (OUT/"montage").mkdir(parents=True,exist_ok=True)
WHITE={"CORNER WEAR","EDGE WEAR","SURFACE / PLAY WEAR","PLAY WEAR DEFECT"}
def is_ph(x,y): return abs(x-50)<=2 and abs(y-50)<=2
def zone_of(nx,ny,t):
    t=t.lower()
    if "corner" in t: return ("T" if ny<0.5 else "B")+("L" if nx<0.5 else "R")
    if "edge" in t:
        d={"LEFT":nx,"RIGHT":1-nx,"TOP":ny,"BOTTOM":1-ny}; return min(d,key=d.get)
    return ("T" if ny<0.5 else "B")+("L" if nx<0.5 else "R")
def box(img):
    rgb=np.asarray(img).astype(np.float32); H,W=rgb.shape[:2]; s=max(20,int(0.04*min(W,H)))
    cor=np.concatenate([rgb[:s,:s].reshape(-1,3),rgb[:s,-s:].reshape(-1,3),rgb[-s:,:s].reshape(-1,3),rgb[-s:,-s:].reshape(-1,3)])
    bg=np.median(cor,axis=0); dist=np.linalg.norm(rgb-bg,axis=2)
    m=(dist>60).astype(np.uint8)*255
    m=cv2.morphologyEx(m,cv2.MORPH_OPEN,np.ones((9,9),np.uint8)); m=cv2.morphologyEx(m,cv2.MORPH_CLOSE,np.ones((25,25),np.uint8))
    n,lab,st,_=cv2.connectedComponentsWithStats(m,8)
    if n<=1: return 0,0,W,H
    i=1+int(np.argmax(st[1:,cv2.CC_STAT_AREA]))
    return int(st[i,0]),int(st[i,1]),int(st[i,0]+st[i,2]),int(st[i,1]+st[i,3])
def tile(a,sz,label):
    a=cv2.resize(a,(sz,sz),interpolation=cv2.INTER_AREA)
    bar=np.full((30,sz,3),20,np.uint8); cv2.putText(bar,label,(6,21),cv2.FONT_HERSHEY_SIMPLEX,0.62,(255,255,255),2,cv2.LINE_AA)
    return np.vstack([bar,a])
def make_montage(img,cardid,side):
    rgb=np.asarray(img); H,W=rgb.shape[:2]; bx0,by0,bx1,by1=box(img); bw,bh=bx1-bx0,by1-by0
    mg=int(0.02*min(bw,bh)); bx0=max(0,bx0-mg);by0=max(0,by0-mg);bx1=min(W,bx1+mg);by1=min(H,by1+mg);bw,bh=bx1-bx0,by1-by0
    strip=max(12,int(0.09*min(bw,bh))); cs=max(24,int(0.17*bw)); sz=440
    def cr(x0,y0,x1,y1): c=rgb[max(0,y0):y1,max(0,x0):x1]; return c if c.size else np.zeros((10,10,3),np.uint8)
    corners={"TL":cr(bx0,by0,bx0+cs,by0+cs),"TR":cr(bx1-cs,by0,bx1,by0+cs),"BL":cr(bx0,by1-cs,bx0+cs,by1),"BR":cr(bx1-cs,by1-cs,bx1,by1)}
    edges={"TOP":cr(bx0,by0,bx1,by0+strip),"BOTTOM":cr(bx0,by1-strip,bx1,by1),"LEFT":cr(bx0,by0,bx0+strip,by1),"RIGHT":cr(bx1-strip,by0,bx1,by1)}
    crow=np.hstack([tile(corners[k],sz,f"{k} CORNER") for k in ("TL","TR","BL","BR")])
    def estrip(a,name):
        if name in ("LEFT","RIGHT"): a=np.rot90(a)
        a=cv2.resize(a,(sz,sz),interpolation=cv2.INTER_AREA)
        bar=np.full((30,sz,3),20,np.uint8); cv2.putText(bar,f"{name} EDGE",(6,21),cv2.FONT_HERSHEY_SIMPLEX,0.62,(255,255,255),2,cv2.LINE_AA)
        return np.vstack([bar,a])
    erow=np.hstack([estrip(edges[k],k) for k in ("TOP","BOTTOM","LEFT","RIGHT")])
    title=np.full((34,crow.shape[1],3),60,np.uint8); cv2.putText(title,f"{cardid} {side.upper()}",(8,24),cv2.FONT_HERSHEY_SIMPLEX,0.7,(255,255,255),2,cv2.LINE_AA)
    return np.vstack([title,crow,np.full((6,crow.shape[1],3),255,np.uint8),erow])

random.seed(3)
paths=glob.glob("data/tag_raw/*/metadata.json"); random.shuffle(paths)
targets=[1,2,3,4,5,6,7,8,9,10]; picked={}; gt={}; manifest=[]
def grade_match(g,t):
    return abs(g-t)<=0.0 or (t not in picked and abs(g-t)<=0.5)
for p in paths:
    if len(picked)>=len(targets): break
    cert=os.path.basename(os.path.dirname(p))
    try: meta=json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: continue
    g=meta.get("grade"); lab=meta.get("grade_label")
    if g is None or not lab: continue
    g=float(g)
    t=next((t for t in targets if t not in picked and abs(g-t)<=0.5), None)
    if t is None: continue
    if not (os.path.exists(f"data/tag_raw/{cert}/images/FRONT_MAIN.jpg") and os.path.exists(f"data/tag_raw/{cert}/images/BACK_MAIN.jpg")): continue
    try:
        sides={}
        for side in ("front","back"):
            img=Image.open(f"data/tag_raw/{cert}/images/{side.upper()}_MAIN.jpg").convert("RGB"); W,Hh=img.size
            Image.fromarray(make_montage(img,cert,side)).save(OUT/"montage"/f"{cert}_{side}.png")
            worn=set()
            for d in meta.get("surface_defects") or []:
                if d.get("side","front")!=side or d.get("defect_type","") not in WHITE or is_ph(d.get("x",0),d.get("y",0)): continue
                nx,ny=d["x"]/W,d["y"]/Hh
                if 0<=nx<=1 and 0<=ny<=1: worn.add(zone_of(nx,ny,d.get("defect_type","")))
            sides[side]=sorted(worn)
    except Exception as e:
        continue
    picked[t]=cert; gt[cert]={"grade":g,"label":lab,"target":t,"front_worn":sides["front"],"back_worn":sides["back"]}
    manifest.append({"cert":cert,"target":t,"grade":g})
(OUT/"manifest.json").write_text(json.dumps(manifest,indent=2))
(OUT/"_gt.json").write_text(json.dumps(gt,indent=2))
print("picked grades:", sorted(picked))
for t in targets:
    c=picked.get(t); print(f"  grade {t}: {c} (TAG {gt[c]['grade']} {gt[c]['label']})" if c else f"  grade {t}: NONE")
