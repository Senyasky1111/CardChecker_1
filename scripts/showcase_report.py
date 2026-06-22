"""Render per-card showcase reports + a detailed markdown table from the grader JSON."""
import sys, json
from pathlib import Path
import numpy as np, cv2
from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES=True
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from src.claude_grade import _card_box   # reuse bg-seg card box
R=Path("runs/grade_showcase"); (R/"reports").mkdir(exist_ok=True)
C=json.load(open(R/"claude_grades.json")); GT=json.load(open(R/"_gt.json")); MAN=json.load(open(R/"manifest.json"))
def clip(x): return max(1.0,min(10.0,x))
def cal(m): return round(clip(1.58*m-4.88),1)
def bucket(g): return "GEM" if g>=9.5 else "NM" if g>=8 else "PLAYED" if g>=5.5 else "BEAT-UP"
LAB={10:"GEM MINT",9.5:"MINT",9:"MINT",8.5:"NM-MINT",8:"NM-MINT",7.5:"NEAR MINT",7:"NEAR MINT",6:"EXC-MINT",5.5:"EXCELLENT",5:"EXCELLENT",4:"VG-EXC",3:"VERY GOOD",2:"GOOD",1:"FAIR"}
def zrect(z,bx0,by0,bx1,by1):
    bw,bh=bx1-bx0,by1-by0; cs=int(0.17*bw); st=int(0.08*min(bw,bh))
    return {"TL":(bx0,by0,bx0+cs,by0+cs),"TR":(bx1-cs,by0,bx1,by0+cs),"BL":(bx0,by1-cs,bx0+cs,by1),"BR":(bx1-cs,by1-cs,bx1,by1),
            "TOP":(bx0,by0,bx1,by0+st),"BOTTOM":(bx0,by1-st,bx1,by1),"LEFT":(bx0,by0,bx0+st,by1),"RIGHT":(bx1-st,by0,bx1,by1)}[z]
def put(c,t,xy,sc=0.6,col=(20,20,20),th=2): cv2.putText(c,t,xy,cv2.FONT_HERSHEY_SIMPLEX,sc,col,th,cv2.LINE_AA)
def side_panel(sd,name,W=470,Hc=760):
    p=np.full((Hc,W,3),250,np.uint8); put(p,name,(16,38),0.7,(0,0,0),2)
    g=sd["grade"]; put(p,f"side grade {g}",(16,92),0.85,((180,30,30) if g<6 else (30,130,30) if g>=8.5 else (200,130,0)),2)
    yy=140
    for k in ("centering","corners","edges","surface"):
        put(p,f"  {k:10} {sd[k]}",(16,yy),0.56,(40,40,40),2); yy+=30
    yy+=12; put(p,"detected wear:",(16,yy),0.6,(0,0,0),2); yy+=28
    if sd["worn_zones"]:
        for z in sd["worn_zones"]: put(p,f"  - {z}",(16,yy),0.5,(180,30,30),1); yy+=24
    else: put(p,"  none",(16,yy),0.55,(30,130,30),2); yy+=24
    yy+=10; put(p,"notes:",(16,yy),0.5,(0,0,0),1); yy+=22
    for ln in [sd.get("zone_notes","")[i:i+46] for i in range(0,min(len(sd.get("zone_notes","")),180),46)]:
        put(p,"  "+ln,(16,yy),0.42,(80,80,80),1); yy+=20
    return p
def render(cert,r,tag):
    blocks=[]
    rawg=r["overall_grade"]; cg=cal(rawg)
    title=np.full((58,1420,3),45,np.uint8)
    put(title,f"{cert}   TAG={tag}   MODEL raw={rawg} -> CALIBRATED={cg} ({bucket(cg)})",(16,38),0.8,(255,255,255),2)
    blocks.append(title)
    for side in ("front","back"):
        sd=r.get(side)
        if sd is None: continue
        img=Image.open(f"data/tag_raw/{cert}/images/{side.upper()}_MAIN.jpg").convert("RGB"); rgb=np.asarray(img).copy()
        bx0,by0,bx1,by1=_card_box(img)
        for z in sd["worn_zones"]:
            x0,y0,x1,y1=zrect(z,bx0,by0,bx1,by1); s=rgb[y0:y1,x0:x1]; rr=np.empty_like(s); rr[:]=(40,40,255); rgb[y0:y1,x0:x1]=(0.6*s+0.4*rr).astype(np.uint8); cv2.rectangle(rgb,(x0,y0),(x1,y1),(40,40,255),max(4,int(0.004*(bx1-bx0))))
        mg=40; card=rgb[max(0,by0-mg):by1+mg,max(0,bx0-mg):bx1+mg]; Hc=760; card=cv2.resize(card,(int(card.shape[1]*Hc/card.shape[0]),Hc),interpolation=cv2.INTER_AREA)
        row=np.hstack([card,side_panel(sd,side.upper())])
        blocks.append(row); blocks.append(np.full((10,row.shape[1],3),120,np.uint8))
    w=max(b.shape[1] for b in blocks); blocks=[np.hstack([b,np.full((b.shape[0],w-b.shape[1],3),255,np.uint8)]) if b.shape[1]<w else b for b in blocks]
    Image.fromarray(np.vstack(blocks)).save(R/"reports"/f"{cert}_g{tag}.png")

# render + build table
rows=[]
for m in sorted(MAN,key=lambda m:m["grade"]):
    cert=m["cert"]; r=C[cert]; tag=GT[cert]["grade"]
    render(cert,r,tag)
    rawg=r["overall_grade"]; cg=cal(rawg)
    fz=",".join(r["front"]["worn_zones"]) or "-"; bz=",".join(r["back"]["worn_zones"]) if r["back"] else "-"
    rows.append((tag,GT[cert]["label"],cert,rawg,cg,bucket(cg),
                 r["front"]["grade"],r["back"]["grade"] if r["back"] else None,fz,bz,r["explanation"]))
# markdown
md=["# Showcase: current grader, 1 card per TAG grade\n",
    "Calibration: grade = clip(1.58*raw - 4.88).  Bucket: GEM>=9.5 / NM>=8 / PLAYED>=5.5 / BEAT-UP<5.5\n",
    "| TAG | label | model raw | **calibrated** | bucket | front | back | front wear | back wear |",
    "|----|----|----|----|----|----|----|----|----|"]
for tag,lab,cert,rawg,cg,bk,fg,bg,fz,bz,_ in rows:
    md.append(f"| {tag} | {lab} | {rawg} | **{cg}** | {bk} | {fg} | {bg} | {fz} | {bz} |")
md.append("\n## Paths per card\n")
for tag,lab,cert,rawg,cg,bk,fg,bg,fz,bz,exp in rows:
    md.append(f"### TAG {tag} ({lab}) — {cert} — model {rawg}->cal {cg} ({bk})")
    md.append(f"- front image: `D:\\CardChecker\\data\\tag_raw\\{cert}\\images\\FRONT_MAIN.jpg`")
    md.append(f"- back image:  `D:\\CardChecker\\data\\tag_raw\\{cert}\\images\\BACK_MAIN.jpg`")
    md.append(f"- zone montages: `D:\\CardChecker\\runs\\grade_showcase\\montage\\{cert}_front.png` / `_back.png`")
    md.append(f"- visual report: `D:\\CardChecker\\runs\\grade_showcase\\reports\\{cert}_g{tag}.png`")
    md.append(f"- explanation: {exp}\n")
(R/"REPORT.md").write_text("\n".join(md),encoding="utf-8")
print("rendered",len(rows),"reports + REPORT.md")
print("\n".join(md[2:4+len(rows)]))
