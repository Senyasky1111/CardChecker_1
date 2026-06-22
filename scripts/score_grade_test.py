"""Score blind Claude-on-crops verdicts vs hidden TAG ground truth. Rich metric suite.
CAVEATS baked in: TAG zone labels are NOISY, ~half flat-invisible, non-exhaustive, back-heavy.
So 'precision vs TAG' is a LOWER bound (we may flag real wear TAG missed) and 'recall vs TAG'
includes wear physically invisible in flat MAIN. Reported with that framing."""
import json, math
from pathlib import Path
R=Path("runs/grade_test")
V=json.load(open(R/"verdicts.json"))
G=json.load(open(R/"_gt_DO_NOT_READ_until_scoring.json"))
CORNERS={"TL","TR","BL","BR"}; EDGES={"TOP","BOTTOM","LEFT","RIGHT"}; ALLZ=CORNERS|EDGES

# ---- GRADE ----
gp=[]; gt=[]
for c in V:
    if c in G and G[c].get("grade") is not None:
        gp.append(V[c]["overall"]); gt.append(float(G[c]["grade"]))
n=len(gp)
def pear(a,b):
    ma=sum(a)/len(a); mb=sum(b)/len(b)
    cov=sum((x-ma)*(y-mb) for x,y in zip(a,b))
    va=math.sqrt(sum((x-ma)**2 for x in a)); vb=math.sqrt(sum((y-mb)**2 for y in b))
    return cov/(va*vb) if va*vb else 0
def spear(a,b):
    def rank(x):
        s=sorted(range(len(x)),key=lambda i:x[i]); r=[0]*len(x)
        for pos,i in enumerate(s): r[i]=pos
        return r
    return pear(rank(a),rank(b))
mae=sum(abs(x-y) for x,y in zip(gp,gt))/n
rmse=math.sqrt(sum((x-y)**2 for x,y in zip(gp,gt))/n)
bias=sum(x-y for x,y in zip(gp,gt))/n
w05=100*sum(1 for x,y in zip(gp,gt) if abs(x-y)<=0.5)/n
w10=100*sum(1 for x,y in zip(gp,gt) if abs(x-y)<=1.0)/n
w15=100*sum(1 for x,y in zip(gp,gt) if abs(x-y)<=1.5)/n
print("="*64); print(f"GRADE (n={n} cards, my overall vs TAG grade)"); print("="*64)
print(f"  MAE={mae:.2f}  RMSE={rmse:.2f}  bias(me-TAG)={bias:+.2f}")
print(f"  Pearson r={pear(gp,gt):.3f}  Spearman={spear(gp,gt):.3f}")
print(f"  within +/-0.5: {w05:.0f}%   +/-1.0: {w10:.0f}%   +/-1.5: {w15:.0f}%")
# per-band
for band in ("gem","mid","low"):
    bp=[(V[c]['overall'],G[c]['grade']) for c in V if G[c]['band']==band]
    if bp:
        m=sum(abs(a-b) for a,b in bp)/len(bp)
        print(f"  band {band:<3} n={len(bp)}  MAE={m:.2f}  mean(me)={sum(a for a,_ in bp)/len(bp):.1f} mean(TAG)={sum(b for _,b in bp)/len(bp):.1f}")

# ---- PER-ZONE DEFECT (binary per zone, vs TAG zones) ----
def zone_stats(side_key, restrict=None):
    tp=fp=fn=tn=0
    for c in V:
        gtw=G[c].get(side_key)
        if gtw is None: continue
        pred=set(V[c][side_key]); gtset=set(gtw)
        zones = ALLZ if restrict is None else restrict
        for z in zones:
            p=z in pred; t=z in gtset
            tp+= p and t; fp+= p and not t; fn+= (not p) and t; tn+= (not p) and (not t)
    prec=tp/max(tp+fp,1); rec=tp/max(tp+fn,1); f1=2*prec*rec/max(prec+rec,1e-9)
    return dict(tp=tp,fp=fp,fn=fn,tn=tn,prec=prec,rec=rec,f1=f1,acc=(tp+tn)/max(tp+fp+fn+tn,1))
def show(name,s):
    print(f"  {name:<22} P={s['prec']:.2f} R={s['rec']:.2f} F1={s['f1']:.2f} acc={s['acc']:.2f}  (tp{s['tp']} fp{s['fp']} fn{s['fn']} tn{s['tn']})")
print("="*64); print("PER-ZONE WEAR vs TAG  (TAG noisy/non-exhaustive -> P is lower bound, R includes invisible wear)"); print("="*64)
show("FRONT all zones", zone_stats("front_worn"))
show("BACK all zones",  zone_stats("back_worn"))
show("FRONT corners",   zone_stats("front_worn",CORNERS))
show("FRONT edges",     zone_stats("front_worn",EDGES))
show("BACK corners",    zone_stats("back_worn",CORNERS))
show("BACK edges",      zone_stats("back_worn",EDGES))

# ---- CLEAN-CARD FALSE POSITIVES (gem cards: should flag ~0) ----
print("="*64); print("CLEAN-CARD behavior (gem band, grade>=9.5): zones I flagged = cry-wolf"); print("="*64)
fpz=0; cards=0
for c in V:
    if G[c]['band']!='gem': continue
    cards+=1
    f=len(V[c]['front_worn']); b=len(V[c]['back_worn'] or [])
    fpz+=f+b
    if f+b>0: print(f"  {c}: flagged {V[c]['front_worn']} front, {V[c]['back_worn']} back")
print(f"  gem cards={cards}, total zones flagged={fpz}, FP-zones/card={fpz/max(cards,1):.2f}  (lower=better, want ~0)")

# ---- detail table ----
print("="*64); print("PER-CARD"); print("="*64)
print(f"  {'cert':10} {'band':4} {'me':>4} {'TAG':>4} {'dG':>5}  front_worn(me) | TAG")
for c in sorted(V,key=lambda c:-G[c]['grade']):
    me=V[c]['overall']; tg=G[c]['grade']
    print(f"  {c:10} {G[c]['band']:4} {me:>4} {tg:>4} {me-tg:>+5.1f}  {','.join(V[c]['front_worn']) or '-':28} | {','.join(G[c]['front_worn']) or '-'}")

# ===== RE-SCORE excluding ungraded (grade_label None / grade 0) =====
import json as _j
def has_grade(c):
    try: m=_j.load(open(f"data/tag_raw/{c}/metadata.json")); return m.get("grade_label") not in (None,"") and float(m.get("grade") or 0)>0
    except: return False
graded=[c for c in V if has_grade(c)]
gp2=[V[c]['overall'] for c in graded]; gt2=[float(G[c]['grade']) for c in graded]; n2=len(gp2)
mae2=sum(abs(a-b) for a,b in zip(gp2,gt2))/n2
rmse2=math.sqrt(sum((a-b)**2 for a,b in zip(gp2,gt2))/n2)
bias2=sum(a-b for a,b in zip(gp2,gt2))/n2
print("\n"+"#"*64); print(f"# CORRECTED GRADE (only {n2} TRULY-GRADED cards; dropped {len(V)-n2} ungraded)"); print("#"*64)
print(f"  MAE={mae2:.2f}  RMSE={rmse2:.2f}  bias(me-TAG)={bias2:+.2f}  Pearson r={pear(gp2,gt2):.3f}  Spearman={spear(gp2,gt2):.3f}")
print(f"  within +/-0.5: {100*sum(1 for a,b in zip(gp2,gt2) if abs(a-b)<=0.5)/n2:.0f}%   +/-1.0: {100*sum(1 for a,b in zip(gp2,gt2) if abs(a-b)<=1.0)/n2:.0f}%   +/-1.5: {100*sum(1 for a,b in zip(gp2,gt2) if abs(a-b)<=1.5)/n2:.0f}%")
for band in ("gem","mid","low"):
    bp=[(V[c]['overall'],G[c]['grade']) for c in graded if G[c]['band']==band]
    if bp: print(f"  band {band:<3} n={len(bp)}  MAE={sum(abs(a-b) for a,b in bp)/len(bp):.2f}  bias={sum(a-b for a,b in bp)/len(bp):+.2f}  mean(me)={sum(a for a,_ in bp)/len(bp):.1f} mean(TAG)={sum(b for _,b in bp)/len(bp):.1f}")
