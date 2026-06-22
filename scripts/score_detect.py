"""STAGE B: map per-zone severities -> wear feature -> grade (CV-calibrated), score vs TAG."""
import argparse, json
from pathlib import Path
ap=argparse.ArgumentParser(); ap.add_argument("--dir",required=True)
ap.add_argument("--det",default="detections.json"); A=ap.parse_args()
R=Path(A.dir); D=json.load(open(R/A.det)); GT=json.load(open(R/"_gt_DO_NOT_READ_until_scoring.json"))
W={"CLEAN":0,"MINOR":1,"MODERATE":3,"HEAVY":6}
def sidewear(z): return sum(W.get(v,0) for v in (z or {}).values())
rows=[]
for c,r in D.items():
    if "front" not in r or c not in GT: continue
    fw=sidewear(r.get("front")); bw=sidewear(r.get("back"))
    feat=0.65*fw+0.35*bw  # weighted total wear (front-heavy like grading)
    rows.append((feat,float(GT[c]["grade"]),GT[c]["band"]))
def clip(x): return max(1.0,min(10.0,x))
def fit(tr):
    n=len(tr); mf=sum(f for f,_,_ in tr)/n; mt=sum(t for _,t,_ in tr)/n
    den=sum((f-mf)**2 for f,_,_ in tr) or 1e-9
    a=sum((f-mf)*(t-mt) for f,t,_ in tr)/den; return a,mt-a*mf
idxA=list(range(0,len(rows),2)); idxB=list(range(1,len(rows),2)); pred=[None]*len(rows)
for tr_i,te_i in [(idxA,idxB),(idxB,idxA)]:
    a,b=fit([rows[i] for i in tr_i])
    for i in te_i: pred[i]=clip(a*rows[i][0]+b)
errs=[(abs(pred[i]-rows[i][1]),rows[i][2]) for i in range(len(rows))]
n=len(errs)
print(f"=== DETECT->GRADE  {A.dir}  (n={n}) ===")
print(f"  overall CV-cal MAE = {sum(e for e,_ in errs)/n:.2f}   within +/-1 = {100*sum(1 for e,_ in errs if e<=1)/n:.0f}%")
for bd in ("gem","nm","ex","low"):
    bi=[i for i in range(len(rows)) if rows[i][2]==bd]
    if bi:
        cm=sum(errs[i][0] for i in bi)/len(bi)
        mp=sum(pred[i] for i in bi)/len(bi); mt=sum(rows[i][1] for i in bi)/len(bi)
        print(f"  band {bd:<4} n={len(bi):<3} calMAE={cm:.2f}  mean(pred)={mp:.1f} mean(TAG)={mt:.1f}")
