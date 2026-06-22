"""Visual defect report: FRONT + BACK, separate per-side grades, NATIVE-scale zone crops
(aspect preserved, no squishing). Overall = front*0.65 + back*0.35."""
import sys, json, os
from pathlib import Path
import numpy as np, cv2
from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
OUT=Path("runs/grade_test/reports"); OUT.mkdir(parents=True,exist_ok=True)
LABELS={10:"GEM MINT",9.5:"MINT",9:"MINT",8.5:"NM-MINT",8:"NM-MINT",7.5:"NEAR MINT",7:"NEAR MINT",6:"EXC-MINT",5:"EXCELLENT",4:"VG-EXC",3:"VERY GOOD",2:"GOOD",1:"POOR"}

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

def zrect(z,bx0,by0,bx1,by1):
    bw,bh=bx1-bx0,by1-by0; cs=int(0.17*bw); st=int(0.08*min(bw,bh))
    return {"TL":(bx0,by0,bx0+cs,by0+cs),"TR":(bx1-cs,by0,bx1,by0+cs),"BL":(bx0,by1-cs,bx0+cs,by1),"BR":(bx1-cs,by1-cs,bx1,by1),
            "TOP":(bx0,by0,bx1,by0+st),"BOTTOM":(bx0,by1-st,bx1,by1),"LEFT":(bx0,by0,bx0+st,by1),"RIGHT":(bx1-st,by0,bx1,by1)}[z]

def put(canvas,txt,xy,sc=0.6,col=(20,20,20),th=2): cv2.putText(canvas,txt,xy,cv2.FONT_HERSHEY_SIMPLEX,sc,col,th,cv2.LINE_AA)

def side_block(img, sd, side_name):
    """[full card w/ markers | grade panel] over [native-scale zone crops]."""
    rgb=np.asarray(img).copy(); bx0,by0,bx1,by1=box(img)
    ov=rgb.copy()
    for z in sd["zones"]:
        x0,y0,x1,y1=zrect(z,bx0,by0,bx1,by1)
        s=ov[y0:y1,x0:x1]; r=np.empty_like(s); r[:]=(40,40,255); ov[y0:y1,x0:x1]=(0.6*s+0.4*r).astype(np.uint8)
        cv2.rectangle(ov,(x0,y0),(x1,y1),(40,40,255),max(4,int(0.004*(bx1-bx0))))
    mg=40; card=ov[max(0,by0-mg):by1+mg, max(0,bx0-mg):bx1+mg]
    Hc=760; card=cv2.resize(card,(int(card.shape[1]*Hc/card.shape[0]),Hc),interpolation=cv2.INTER_AREA)
    pw=460; panel=np.full((Hc,pw,3),250,np.uint8)
    put(panel,f"{side_name} side",(16,40),0.75,(0,0,0),2)
    g=sd["grade"]; put(panel,f"GRADE {g}",(16,98),1.0,((180,30,30) if g<6 else (30,130,30) if g>=8.5 else (200,130,0)),3)
    put(panel,LABELS.get(g,""),(16,128),0.55,(90,90,90),2)
    put(panel,"Pillars:",(16,178),0.6,(0,0,0),2); yy=210
    for k in ("centering","corners","edges","surface"):
        put(panel,f"  {k:10} {sd['pillars'][k]}",(16,yy),0.56,(40,40,40),2); yy+=30
    yy+=16; put(panel,"Detected wear:",(16,yy),0.6,(0,0,0),2); yy+=30
    if sd["zones"]:
        for z,t in sd["zones"].items(): put(panel,f"  - {z}: {t}",(16,yy),0.48,(180,30,30),1); yy+=25
    else: put(panel,"  none - clean side",(16,yy),0.55,(30,130,30),2)
    head=np.hstack([card,panel])
    # NATIVE-scale zone crops (aspect preserved, uniform factor)
    W=img.size[0]; bw=bx1-bx0; bh=by1-by0; cs=int(0.17*bw); st=int(0.08*min(bw,bh))
    f=min(1.0, 1500.0/max(bw,bh))             # uniform downscale only if huge; keeps aspect & relative scale
    def crop(z):
        x0,y0,x1,y1=zrect(z,bx0,by0,bx1,by1); c=rgb[y0:y1,x0:x1]
        if z in ("LEFT","RIGHT"): c=np.rot90(c)     # make vertical edges horizontal for stacking (no scale change)
        nw=max(1,int(c.shape[1]*f)); nh=max(1,int(c.shape[0]*f))
        c=cv2.resize(c,(nw,nh),interpolation=cv2.INTER_AREA)
        bar=np.full((26,c.shape[1],3),30,np.uint8); put(bar,z,(6,19),0.55,(255,255,255),2)
        if z in [zz for zz in sd["zones"]]:
            cv2.rectangle(c,(0,0),(c.shape[1]-1,c.shape[0]-1),(40,40,255),5)
        return np.vstack([bar,c])
    corner_imgs=[crop(z) for z in ("TL","TR","BL","BR")]
    ch=max(x.shape[0] for x in corner_imgs)
    corner_imgs=[np.vstack([x,np.full((ch-x.shape[0],x.shape[1],3),255,np.uint8)]) for x in corner_imgs]
    crow=np.hstack([np.hstack([x,np.full((x.shape[0],8,3),255,np.uint8)]) for x in corner_imgs])
    edge_imgs=[crop(z) for z in ("TOP","BOTTOM","LEFT","RIGHT")]
    fullw=max(crow.shape[1], max(e.shape[1] for e in edge_imgs))
    def pad(a): return np.hstack([a,np.full((a.shape[0],fullw-a.shape[1],3),255,np.uint8)]) if a.shape[1]<fullw else a[:, :fullw]
    blocks=[pad(crow)]+[np.vstack([np.full((6,fullw,3),255,np.uint8),pad(e)]) for e in edge_imgs]
    zones_img=np.vstack(blocks)
    head=pad(head)
    return np.vstack([head, np.full((10,fullw,3),200,np.uint8), zones_img])

def render(cert, V):
    blocks=[]
    overall=V["overall"]
    title=np.full((54,1400,3),50,np.uint8)
    put(title,f"{cert}   OVERALL GRADE {overall}   (front {V['front']['grade']} x0.65 + back {V['back']['grade']} x0.35)",(16,36),0.8,(255,255,255),2)
    blocks.append(title)
    for side in ("front","back"):
        ip=f"data/tag_raw/{cert}/images/{side.upper()}_MAIN.jpg"
        if not os.path.exists(ip): continue
        img=Image.open(ip).convert("RGB")
        b=side_block(img, V[side], side.upper())
        blocks.append(b); blocks.append(np.full((16,b.shape[1],3),120,np.uint8))
    w=max(b.shape[1] for b in blocks)
    blocks=[np.hstack([b,np.full((b.shape[0],w-b.shape[1],3),255,np.uint8)]) if b.shape[1]<w else b for b in blocks]
    Image.fromarray(np.vstack(blocks)).save(OUT/f"{cert}_report.png")
    print(f"{cert}: overall {overall} (F{V['front']['grade']}/B{V['back']['grade']})")

P=lambda c,co,e,s: {"centering":c,"corners":co,"edges":e,"surface":s}
DATA={
 "S9743026":{"overall":9.5,"front":{"grade":10,"pillars":P(10,10,9.5,9.5),"zones":{}},"back":{"grade":9,"pillars":P(9,9,9,9),"zones":{}}},
 "U8540608":{"overall":9.5,"front":{"grade":9.5,"pillars":P(9.5,9.5,9.5,9.5),"zones":{}},"back":{"grade":9,"pillars":P(9,9,9,9),"zones":{}}},
 "Q2651715":{"overall":8,"front":{"grade":8,"pillars":P(9,8.5,8,9),"zones":{"TOP":"light edge whitening"}},"back":{"grade":8.5,"pillars":P(9,9,8.5,9),"zones":{}}},
 "E4742315":{"overall":5.5,"front":{"grade":5,"pillars":P(8,6,5,7),"zones":{"TL":"corner whitening","BR":"corner whitening","TOP":"edge whitening","LEFT":"edge whitening","RIGHT":"edge whitening"}},"back":{"grade":7,"pillars":P(8,8,7,8),"zones":{"BOTTOM":"edge whitening","RIGHT":"edge whitening"}}},
 "H4222464":{"overall":5,"front":{"grade":4.5,"pillars":P(8,5,5,7),"zones":{"TL":"whitening+rounding","TR":"whitening+rounding","BL":"whitening+rounding","BR":"whitening+rounding","TOP":"edge whitening","LEFT":"edge whitening","RIGHT":"edge whitening"}},"back":{"grade":7,"pillars":P(8,8,7,8),"zones":{"LEFT":"edge whitening","BOTTOM":"edge whitening"}}},
 "U5140638":{"overall":2.5,"front":{"grade":2.5,"pillars":P(7,2.5,2.5,5),"zones":{z:"heavy whitening" for z in ("TL","TR","BL","BR","TOP","BOTTOM","LEFT","RIGHT")}},"back":{"grade":3,"pillars":P(7,3,3,5),"zones":{z:"heavy whitening" for z in ("TL","TR","BL","BR","TOP","BOTTOM","LEFT","RIGHT")}}},
}
for c,v in DATA.items(): render(c,v)
print(f"\nreports -> {OUT}/")
