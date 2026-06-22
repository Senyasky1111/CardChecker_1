import sys, json
from pathlib import Path
import numpy as np, cv2
from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES=True
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from src.claude_grade import _card_box
R=Path("runs/grade_test_100"); (R/"chain_reports").mkdir(exist_ok=True)
S=json.load(open(R/"chain_showcase.json"))
def clip(x): return max(1.0,min(10.0,x))
def cal(m): return round(clip(1.58*m-4.88),1)
def dist_str(d):
    if not d: return "-"
    return " ".join(f"{x['grade']}:{x['prob']:.2f}" for x in sorted(d,key=lambda x:-x['prob']))
def modheavy(z): return [f"{k}:{v}" for k,v in (z or {}).items() if v in ("MODERATE","HEAVY")]
def zrect(zn,bx0,by0,bx1,by1):
    bw,bh=bx1-bx0,by1-by0; cs=int(0.17*bw); st=int(0.08*min(bw,bh))
    return {"TL":(bx0,by0,bx0+cs,by0+cs),"TR":(bx1-cs,by0,bx1,by0+cs),"BL":(bx0,by1-cs,bx0+cs,by1),"BR":(bx1-cs,by1-cs,bx1,by1),
            "TOP":(bx0,by0,bx1,by0+st),"BOTTOM":(bx0,by1-st,bx1,by1),"LEFT":(bx0,by0,bx0+st,by1),"RIGHT":(bx1-st,by0,bx1,by1)}[zn]
def put(c,t,xy,sc=0.55,col=(20,20,20),th=1): cv2.putText(c,t,xy,cv2.FONT_HERSHEY_SIMPLEX,sc,col,th,cv2.LINE_AA)
def render(cert,o):
    tag=o["tag"]; hol=o["holistic"]; det=o["detector"]; ch=o["chain"]
    cards=[]
    for side in ("front","back"):
        sd=ch.get(side)
        ip=f"data/tag_raw/{cert}/images/{side.upper()}_MAIN.jpg"
        if not Path(ip).exists(): continue
        img=Image.open(ip).convert("RGB"); rgb=np.asarray(img).copy(); bx0,by0,bx1,by1=_card_box(img)
        for z in (sd["worn_zones"] if sd else []):
            x0,y0,x1,y1=zrect(z,bx0,by0,bx1,by1); s=rgb[y0:y1,x0:x1]; rr=np.empty_like(s); rr[:]=(40,40,255)
            rgb[y0:y1,x0:x1]=(0.6*s+0.4*rr).astype(np.uint8); cv2.rectangle(rgb,(x0,y0),(x1,y1),(40,40,255),max(3,int(0.004*(bx1-bx0))))
        mg=40; cc=rgb[max(0,by0-mg):by1+mg,max(0,bx0-mg):bx1+mg]; h=620; cc=cv2.resize(cc,(int(cc.shape[1]*h/cc.shape[0]),h),interpolation=cv2.INTER_AREA)
        cards.append(cc)
    cardrow=np.hstack(cards) if cards else np.zeros((620,400,3),np.uint8)
    W=1500; panel=np.full((cardrow.shape[0],W,3),250,np.uint8); y=34
    put(panel,f"{cert}   TAG GRADE = {tag}",(14,y),0.8,(0,0,0),2); y+=44
    put(panel,f"HOLISTIC: raw {hol['overall_grade']} -> cal {cal(hol['overall_grade'])}   (front {hol['front']['grade']} / back {hol['back']['grade'] if hol['back'] else '-'})",(14,y),0.6,(150,90,0),2); y+=26
    put(panel,f"   prob-dist: {dist_str(hol.get('grade_distribution'))}",(14,y),0.5,(120,120,120),1); y+=24
    put(panel,f"   zones: F[{','.join(hol['front']['worn_zones']) or '-'}] B[{','.join(hol['back']['worn_zones']) if hol['back'] else '-'}]",(14,y),0.48,(120,120,120),1); y+=30
    put(panel,"DETECTOR (MODERATE+ findings):",(14,y),0.6,(150,30,30),2); y+=24
    put(panel,f"   FRONT: {', '.join(modheavy(det.get('front'))) or 'none'}",(14,y),0.46,(150,30,30),1); y+=22
    put(panel,f"   BACK:  {', '.join(modheavy(det.get('back'))) or 'none'}",(14,y),0.46,(150,30,30),1); y+=30
    put(panel,f"CHAIN (re-grade w/ evidence): raw {ch['overall_grade']} -> cal {cal(ch['overall_grade'])}   (front {ch['front']['grade']} / back {ch['back']['grade'] if ch['back'] else '-'})",(14,y),0.6,(30,120,30),2); y+=26
    put(panel,f"   prob-dist: {dist_str(ch.get('grade_distribution'))}",(14,y),0.5,(120,120,120),1); y+=24
    put(panel,f"   zones: F[{','.join(ch['front']['worn_zones']) or '-'}] B[{','.join(ch['back']['worn_zones']) if ch['back'] else '-'}]",(14,y),0.48,(120,120,120),1); y+=30
    # explanation wrapped
    put(panel,"chain explanation:",(14,y),0.5,(0,0,0),1); y+=22
    exp=ch.get("explanation","")
    for i in range(0,min(len(exp),520),64):
        put(panel,"  "+exp[i:i+64],(14,y),0.42,(70,70,70),1); y+=18
    out=np.vstack([cardrow, np.full((6,max(cardrow.shape[1],W),3),200,np.uint8)]) if cardrow.shape[1]>=W else cardrow
    full=np.vstack([np.hstack([cardrow,np.full((cardrow.shape[0],max(0,W-cardrow.shape[1]),3),255,np.uint8)]) if cardrow.shape[1]<W else cardrow, panel*0+ panel]) if False else None
    # stack cards over panel (pad widths)
    w=max(cardrow.shape[1],panel.shape[1])
    def padw(a): return np.hstack([a,np.full((a.shape[0],w-a.shape[1],3),255,np.uint8)]) if a.shape[1]<w else a
    Image.fromarray(np.vstack([padw(cardrow),padw(panel)])).save(R/"chain_reports"/f"{cert}_TAG{tag}.png")
md=["# Chain analysis: 10 medium cards (TAG 5-8)\n","cal = 1.58*raw-4.88\n",
    "| TAG | holistic raw->cal | CHAIN raw->cal | holistic dist | chain dist | detector MODERATE+ (F/B) |",
    "|---|---|---|---|---|---|"]
for cert,o in sorted(S.items(),key=lambda kv:kv[1]["tag"]):
    render(cert,o)
    hol=o["holistic"]; ch=o["chain"]; det=o["detector"]
    md.append(f"| {o['tag']} | {hol['overall_grade']}->{cal(hol['overall_grade'])} | {ch['overall_grade']}->{cal(ch['overall_grade'])} | {dist_str(hol.get('grade_distribution'))} | {dist_str(ch.get('grade_distribution'))} | {len(modheavy(det.get('front')))}/{len(modheavy(det.get('back')))} |")
md.append("\n## Per-card paths\n")
for cert,o in sorted(S.items(),key=lambda kv:kv[1]["tag"]):
    md.append(f"- TAG {o['tag']}  {cert}  ->  `D:\\CardChecker\\runs\\grade_test_100\\chain_reports\\{cert}_TAG{o['tag']}.png`")
    md.append(f"    card: `D:\\CardChecker\\data\\tag_raw\\{cert}\\images\\FRONT_MAIN.jpg` / BACK_MAIN.jpg")
(R/"CHAIN_REPORT.md").write_text("\n".join(md),encoding="utf-8")
print("rendered",len(S),"-> runs/grade_test_100/chain_reports/ + CHAIN_REPORT.md")
print("\n".join(md[2:4+len(S)]))
