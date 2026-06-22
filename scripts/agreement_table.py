"""Defect-count & grade agreement: my blind verdicts vs TAG, per side. Honest framing:
TAG labels are non-exhaustive + 86% back-weighted, so disagreement != my error."""
import json, math
from pathlib import Path
R=Path("runs/grade_test"); V=json.load(open(R/"verdicts.json"))
WHITE={"CORNER WEAR","EDGE WEAR","SURFACE / PLAY WEAR","PLAY WEAR DEFECT"}
def is_ph(x,y): return abs(x-50)<=2 and abs(y-50)<=2
def zone_of(nx,ny,t):
    t=t.lower()
    if "corner" in t: return ("T" if ny<0.5 else "B")+("L" if nx<0.5 else "R")
    if "edge" in t:
        d={"LEFT":nx,"RIGHT":1-nx,"TOP":ny,"BOTTOM":1-ny}; return min(d,key=d.get)
    return ("T" if ny<0.5 else "B")+("L" if nx<0.5 else "R")
def tag_zones(cert,side):
    m=json.load(open(f"data/tag_raw/{cert}/metadata.json")); W,H=4380,6080
    try:
        from PIL import Image; W,H=Image.open(f"data/tag_raw/{cert}/images/{side.upper()}_MAIN.jpg").size
    except: pass
    z=set()
    for d in m.get("surface_defects") or []:
        if d.get("side","front")!=side or d.get("defect_type","") not in WHITE: continue
        if is_ph(d.get("x",0),d.get("y",0)): continue
        nx,ny=d["x"]/W,d["y"]/H
        if 0<=nx<=1 and 0<=ny<=1: z.add(zone_of(nx,ny,d.get("defect_type","")))
    return z, (m.get("grade"), m.get("grade_label"))

rows=[]
for c in V:
    fz,(g,lab)=tag_zones(c,"front"); bz,_=tag_zones(c,"back")
    rows.append(dict(c=c,grade=g,lab=lab,
        mf=len(V[c]["front_worn"]), tf=len(fz),
        mb=len(V[c]["back_worn"] or []), tb=len(bz),
        mg=V[c]["overall"]))
print(f"{'cert':10} {'TAGg':>5} {'meG':>4} {'dG':>5} | {'myF':>3} {'tagF':>4} | {'myB':>3} {'tagB':>4}")
print("-"*60)
for r in sorted(rows,key=lambda r:-(r['grade'] or 0)):
    dg = f"{r['mg']-r['grade']:+.1f}" if r['grade'] and r['lab'] else "  -"
    print(f"{r['c']:10} {str(r['grade']):>5} {r['mg']:>4} {dg:>5} | {r['mf']:>3} {r['tf']:>4} | {r['mb']:>3} {r['tb']:>4}")

graded=[r for r in rows if r['grade'] and r['lab']]
def mae(k1,k2,rs): return sum(abs(r[k1]-r[k2]) for r in rs)/len(rs)
print("\n== SUMMARY (graded cards only, n=%d) =="%len(graded))
print(f"  grade MAE          : {mae('mg','grade',graded):.2f}")
print(f"  front defect-count MAE (me vs TAG): {mae('mf','tf',rows):.2f}   mean(me)={sum(r['mf'] for r in rows)/len(rows):.1f} mean(TAG)={sum(r['tf'] for r in rows)/len(rows):.1f}")
print(f"  back  defect-count MAE (me vs TAG): {mae('mb','tb',rows):.2f}   mean(me)={sum(r['mb'] for r in rows)/len(rows):.1f} mean(TAG)={sum(r['tb'] for r in rows)/len(rows):.1f}")
# directional bias
fover=sum(1 for r in rows if r['mf']>r['tf']); funder=sum(1 for r in rows if r['mf']<r['tf'])
bover=sum(1 for r in rows if r['mb']>r['tb']); bunder=sum(1 for r in rows if r['mb']<r['tb'])
print(f"  FRONT: I flag MORE than TAG on {fover} cards, FEWER on {funder}")
print(f"  BACK : I flag MORE than TAG on {bover} cards, FEWER on {bunder}  <- TAG labels 86% on back; I under-call back")
