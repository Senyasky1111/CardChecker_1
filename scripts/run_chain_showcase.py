import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for ln in Path(".env").read_text().splitlines():
    if ln.strip() and not ln.startswith("#") and "=" in ln:
        k,v=ln.split("=",1); os.environ.setdefault(k.strip(),v.strip())
from src.claude_grade import ClaudeGrader, prep_full_card
R=Path("runs/grade_test_100"); MD=R/"montage"; fulldir=R/"fullcard"
H=json.load(open(R/"claude_grades.json")); D=json.load(open(R/"detections.json")); GT=json.load(open(R/"_gt_DO_NOT_READ_until_scoring.json"))
# 10 cards TAG in [5,8]
cand=[c for c in H if "overall_grade" in H[c] and c in D and "front" in D[c] and c in GT and 5.0<=float(GT[c]["grade"])<=8.0]
cand=sorted(cand, key=lambda c: float(GT[c]["grade"]))[:10] if len(cand)>10 else cand
import random; random.seed(1)
if len(cand)>10: cand=sorted(random.sample(cand,10), key=lambda c: float(GT[c]["grade"]))
g=ClaudeGrader(thinking=True)
out={}
for c in cand:
    fp=str(MD/f"{c}_front.png"); bp=str(MD/f"{c}_back.png")
    ff=prep_full_card(f"data/tag_raw/{c}/images/FRONT_MAIN.jpg",str(fulldir/f"{c}_front.png"))
    bf=prep_full_card(f"data/tag_raw/{c}/images/BACK_MAIN.jpg",str(fulldir/f"{c}_back.png"))
    ch=g.regrade_with_evidence(D[c],fp,bp if os.path.exists(bp) else None,front_full=ff,back_full=bf)
    out[c]={"tag":float(GT[c]["grade"]),"holistic":H[c],"detector":D[c],"chain":ch}
    print(f"{c}: TAG {GT[c]['grade']}  holistic {H[c]['overall_grade']} -> chain {ch.get('overall_grade')}",flush=True)
(R/"chain_showcase.json").write_text(json.dumps(out,indent=2))
print(f"\nsaved {len(out)} -> runs/grade_test_100/chain_showcase.json")
