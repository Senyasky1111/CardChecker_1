"""Compare Claude-API grades vs TAG ground truth (and vs my in-session blind verdicts)."""
import json, math
from pathlib import Path
R = Path("runs/grade_test")
C = json.load(open(R / "claude_grades.json"))
V = json.load(open(R / "verdicts.json")) if (R / "verdicts.json").exists() else {}

def has_grade(cert):
    try:
        m = json.load(open(f"data/tag_raw/{cert}/metadata.json"))
        return m.get("grade_label") not in (None, "") and float(m.get("grade") or 0) > 0, float(m.get("grade") or 0)
    except Exception:
        return False, None

def pear(a, b):
    ma, mb = sum(a)/len(a), sum(b)/len(b)
    cov = sum((x-ma)*(y-mb) for x, y in zip(a, b))
    va = math.sqrt(sum((x-ma)**2 for x in a)); vb = math.sqrt(sum((y-mb)**2 for y in b))
    return cov/(va*vb) if va*vb else 0

rows = []
for cert, r in C.items():
    if "overall_grade" not in r:
        print("ERR", cert, r.get("error")); continue
    ok, g = has_grade(cert)
    rows.append((cert, r["overall_grade"], g if ok else None, V.get(cert, {}).get("overall")))

graded = [(c, a, t, m) for c, a, t, m in rows if t is not None]
print(f"{'cert':10} {'API':>5} {'TAG':>5} {'mine':>5}  {'API-TAG':>8}")
for c, a, t, m in sorted(graded, key=lambda x: -(x[2] or 0)):
    print(f"{c:10} {a:>5} {t:>5} {str(m):>5}  {a-t:>+8.1f}")

ap = [a for _, a, t, _ in graded]; tg = [t for _, a, t, _ in graded]
mae = sum(abs(a-t) for a, t in zip(ap, tg))/len(ap)
bias = sum(a-t for a, t in zip(ap, tg))/len(ap)
print(f"\nAPI vs TAG (n={len(graded)}):  MAE={mae:.2f}  bias(API-TAG)={bias:+.2f}  r={pear(ap,tg):.3f}")
print(f"  within +/-1.0: {100*sum(1 for a,t in zip(ap,tg) if abs(a-t)<=1)/len(ap):.0f}%   +/-1.5: {100*sum(1 for a,t in zip(ap,tg) if abs(a-t)<=1.5)/len(ap):.0f}%")
# API vs my blind
both = [(a, m) for _, a, t, m in rows if m is not None]
if both:
    am = sum(abs(a-m) for a, m in both)/len(both)
    print(f"API vs my-blind (n={len(both)}): MAE={am:.2f}  bias(API-mine)={sum(a-m for a,m in both)/len(both):+.2f}")
# clean-card FP: gem cards (TAG>=9.5) — how many API flagged any zone
gem = [(c, r) for c, r in C.items() if "overall_grade" in r and (has_grade(c)[1] or 0) >= 9.5]
fpz = sum(len(r["front"]["worn_zones"]) + (len(r["back"]["worn_zones"]) if r["back"] else 0) for _, r in gem)
print(f"\nCLEAN cards (TAG>=9.5): {len(gem)} cards, API flagged {fpz} zones total ({fpz/max(len(gem),1):.1f}/card)")
