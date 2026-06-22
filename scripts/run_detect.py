"""STAGE A: run the per-zone detector over a montage dir -> detections.json."""
import argparse, json, os, sys, glob
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
ap=argparse.ArgumentParser(); ap.add_argument("--montage-dir",required=True); ap.add_argument("--n",type=int,default=100)
ap.add_argument("--workers",type=int,default=6); ap.add_argument("--out",required=True); A=ap.parse_args()
fronts=sorted(glob.glob(f"{A.montage_dir}/*_front.png"))[:A.n]
certs=[Path(f).name[:-len("_front.png")] for f in fronts]
g=ClaudeGrader(thinking=True)
fulldir=Path(A.montage_dir).parent/"fullcard"; fulldir.mkdir(parents=True,exist_ok=True)
def one(c):
    fp=f"{A.montage_dir}/{c}_front.png"; bp=f"{A.montage_dir}/{c}_back.png"
    ff=prep_full_card(f"data/tag_raw/{c}/images/FRONT_MAIN.jpg",str(fulldir/f"{c}_front.png"))
    bf=prep_full_card(f"data/tag_raw/{c}/images/BACK_MAIN.jpg",str(fulldir/f"{c}_back.png"))
    try: return c,g.detect_zones(fp,bp if os.path.exists(bp) else None,front_full=ff,back_full=bf)
    except Exception as e: return c,{"error":str(e)}
res={}; tin=tout=0; done=0
with ThreadPoolExecutor(max_workers=A.workers) as ex:
    for c,r in (f.result() for f in as_completed([ex.submit(one,c) for c in certs])):
        res[c]=r; done+=1
        if "_usage" in r: tin+=r["_usage"]["input"]; tout+=r["_usage"]["output"]
        nf=sum(1 for v in (r.get("front") or {}).values() if v!="CLEAN")
        print(f"[{done}/{len(certs)}] {c}: front non-clean zones={nf}",flush=True)
Path(A.out).write_text(json.dumps(res,indent=2))
cost=tin/1e6*5+tout/1e6*25
print(f"\nDONE -> {A.out}  cost=${cost:.2f} (~${cost/max(done,1):.3f}/card)")
