"""User's flow: holistic grade -> if >=GEM_THR keep it; else re-grade WITH detector evidence fed back."""
import json, os, sys, glob
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
def _env():
    f=Path(__file__).resolve().parent.parent/".env"
    for ln in (f.read_text().splitlines() if f.exists() else []):
        if ln.strip() and not ln.startswith("#") and "=" in ln:
            k,v=ln.split("=",1); os.environ.setdefault(k.strip(),v.strip())
_env()
from src.claude_grade import ClaudeGrader, prep_full_card
R=Path("runs/grade_test_100"); MD=R/"montage"
H=json.load(open(R/"claude_grades.json")); D=json.load(open(R/"detections.json"))
GEM_THR=8.5   # holistic raw >= this -> trust holistic (good card); else escalate
g=ClaudeGrader(thinking=True)
fulldir=R/"fullcard"
certs=[c for c in H if "overall_grade" in H[c] and c in D and "front" in D[c]]
routed=[c for c in certs if H[c]["overall_grade"] < GEM_THR]
print(f"{len(certs)} cards; trust-holistic={len(certs)-len(routed)} (raw>={GEM_THR}); escalate-to-regrade={len(routed)}")
def one(c):
    fp=str(MD/f"{c}_front.png"); bp=str(MD/f"{c}_back.png")
    ff=prep_full_card(f"data/tag_raw/{c}/images/FRONT_MAIN.jpg",str(fulldir/f"{c}_front.png"))
    bf=prep_full_card(f"data/tag_raw/{c}/images/BACK_MAIN.jpg",str(fulldir/f"{c}_back.png"))
    try: return c,g.regrade_with_evidence(D[c],fp,bp if os.path.exists(bp) else None,front_full=ff,back_full=bf)
    except Exception as e: return c,{"error":str(e)}
final={}
for c in certs:
    if c not in routed: final[c]={"overall_grade":H[c]["overall_grade"],"_src":"holistic"}
tin=tout=0; done=0
with ThreadPoolExecutor(max_workers=6) as ex:
    for c,r in (f.result() for f in as_completed([ex.submit(one,c) for c in routed])):
        if "overall_grade" in r: final[c]={"overall_grade":r["overall_grade"],"_src":"regrade"}
        else: final[c]={"overall_grade":H[c]["overall_grade"],"_src":"holistic(regrade_err)"}
        if "_usage" in r: tin+=r["_usage"]["input"]; tout+=r["_usage"]["output"]
        done+=1; print(f"[{done}/{len(routed)}] {c}: holistic {H[c]['overall_grade']} -> regrade {r.get('overall_grade','ERR')}",flush=True)
Path(R/"routed_grades.json").write_text(json.dumps(final,indent=2))
print(f"\nDONE  regrade-cost=${(tin/1e6*5+tout/1e6*25):.2f}")
