import json
from pathlib import Path
R=Path("runs/grade_test_100")
F=json.load(open(R/"routed_grades.json")); GT=json.load(open(R/"_gt_DO_NOT_READ_until_scoring.json"))
rows=[(F[c]["overall_grade"],float(GT[c]["grade"]),GT[c]["band"]) for c in F if c in GT]
def clip(x): return max(1.0,min(10.0,x))
def fit(tr):
    n=len(tr);mp=sum(p for p,_,_ in tr)/n;mt=sum(t for _,t,_ in tr)/n
    den=sum((p-mp)**2 for p,_,_ in tr) or 1e-9;a=sum((p-mp)*(t-mt) for p,t,_ in tr)/den;return a,mt-a*mp
iA=list(range(0,len(rows),2));iB=list(range(1,len(rows),2));pred=[None]*len(rows)
for tr,te in [(iA,iB),(iB,iA)]:
    a,b=fit([rows[i] for i in tr])
    for i in te: pred[i]=clip(a*rows[i][0]+b)
e=[(abs(pred[i]-rows[i][1]),rows[i][2]) for i in range(len(rows))]; n=len(e)
dang=sum(1 for i in range(len(rows)) if rows[i][1]<5.5 and pred[i]>=7)
print("BASELINE holistic:   overall=0.97 w1=73%  gem=0.84 nm=0.67 ex=0.89 low=1.90  dangerous=5")
bb={bd:[e[i][0] for i in range(len(rows)) if rows[i][2]==bd] for bd in ("gem","nm","ex","low")}
print(f"ROUTED (holistic+regrade): overall={sum(x for x,_ in e)/n:.2f} w1={100*sum(1 for x,_ in e if x<=1)/n:.0f}%  "+
      " ".join(f"{bd}={sum(v)/len(v):.2f}" for bd,v in bb.items() if v)+f"  dangerous(worn->NM+)={dang}")
