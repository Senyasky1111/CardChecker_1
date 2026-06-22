import os, json, glob, math
from collections import Counter, defaultdict

ROOT = r"d:/CardChecker/data/tag_raw"
NATIVE_W, NATIVE_H = 4463, 6161

dirs = [d for d in os.listdir(ROOT) if os.path.isdir(os.path.join(ROOT, d))]
total_cards = len(dirs)
cards_with_meta = 0
cards_with_grade = 0
grade_counter = Counter()

total_defects = 0
defect_type_counter = Counter()
side_counter = Counter()
type_by_side = defaultdict(Counter)

# coordinate range tracking
xs, ys = [], []
placeholder_count = 0
nonplaceholder = 0

# also inspect corners/edges/surface arrays presence
arr_presence = Counter()
dings_sum = Counter()

# bucket mapping
def bucket(dt):
    t = dt.upper()
    if "WHITEN" in t:
        return "whitening"
    if "CORNER" in t:
        return "corner"
    if "EDGE" in t:
        return "edge"
    if any(k in t for k in ["SCRATCH","SURFACE","PRINT","STAIN","DENT","INDENT","CREASE","SCUFF","DING","HOLO","FOIL","GLOSS"]):
        return "surface"
    return "other"

bucket_counter = Counter()
# need to know coord convention before classifying placeholders; assume pixels, also compute a normalized-0..100 placeholder test fallback
# We'll detect convention from max values.

raw_records = []  # store (x,y,type,side) to reprocess for placeholder after convention known

n = 0
for d in dirs:
    mp = os.path.join(ROOT, d, "metadata.json")
    if not os.path.exists(mp):
        continue
    try:
        with open(mp, "r", encoding="utf-8") as f:
            m = json.load(f)
    except Exception:
        continue
    cards_with_meta += 1
    g = m.get("grade", 0)
    try:
        gf = float(g)
    except Exception:
        gf = 0.0
    if gf and gf > 0:
        cards_with_grade += 1
        grade_counter[gf] += 1
    for key in ("corners","edges","surface","surface_defects"):
        if isinstance(m.get(key), list) and len(m[key]) > 0:
            arr_presence[key] += 1
    for key in ("dings_corners_front","dings_corners_back","dings_edges_front","dings_edges_back","dings_surface_front","dings_surface_back"):
        v = m.get(key, 0) or 0
        try: dings_sum[key] += int(v)
        except Exception: pass

    sd = m.get("surface_defects", []) or []
    for rec in sd:
        if not isinstance(rec, dict):
            continue
        dt = str(rec.get("defect_type", "")).strip()
        side = str(rec.get("side", "")).strip().lower()
        x = rec.get("x", None); y = rec.get("y", None)
        total_defects += 1
        defect_type_counter[dt] += 1
        side_counter[side] += 1
        type_by_side[side][dt] += 1
        bucket_counter[bucket(dt)] += 1
        if isinstance(x,(int,float)): xs.append(x)
        if isinstance(y,(int,float)): ys.append(y)
        raw_records.append((x,y,dt,side))

# coordinate convention
def pct(vals, p):
    if not vals: return None
    s = sorted(vals); i = min(len(s)-1, int(p*len(s)))
    return s[i]

xmax = max(xs) if xs else 0
ymax = max(ys) if ys else 0
x99 = pct(xs,0.99); y99 = pct(ys,0.99)
convention = "pixels" if (xmax > 100 or ymax > 100) else "0..100"

# placeholder detection per convention
placeholder = 0
for (x,y,dt,side) in raw_records:
    if x is None or y is None: continue
    if convention == "0..100":
        if (abs(x-50)<=25 and abs(y-50)<=25) or (abs(x)<=5 and abs(y)<=5):
            placeholder += 1
    else:
        nx = x / NATIVE_W * 100.0
        ny = y / NATIVE_H * 100.0
        if (abs(nx-50)<=25 and abs(ny-50)<=25) or (abs(nx)<=5 and abs(ny)<=5):
            placeholder += 1

print("=== TAG DATA DISTRIBUTION ===")
print(f"total cert dirs: {total_cards}")
print(f"cards with metadata.json: {cards_with_meta}")
print(f"cards with grade>0: {cards_with_grade}  ({100*cards_with_grade/max(1,cards_with_meta):.1f}% of meta)")
print()
print("--- coordinate convention ---")
print(f"x range max={xmax}  y range max={ymax}  x99={x99} y99={y99}")
print(f"=> CONVENTION: {convention}  (native {NATIVE_W}x{NATIVE_H})")
print()
print(f"--- defects ---")
print(f"total defects: {total_defects}")
print(f"placeholders ((50,50)+/-25 or near 0,0): {placeholder}  ({100*placeholder/max(1,total_defects):.1f}%)")
print(f"avg defects/card(meta): {total_defects/max(1,cards_with_meta):.2f}")
print()
print("--- defect_type counts (all) ---")
for dt,c in defect_type_counter.most_common():
    print(f"  {c:8d}  {100*c/max(1,total_defects):5.1f}%  {dt!r}")
print()
print("--- side breakdown ---")
for s,c in side_counter.most_common():
    print(f"  {s!r}: {c} ({100*c/max(1,total_defects):.1f}%)")
print()
print("--- buckets {whitening,edge,corner,surface,other} ---")
for b in ["whitening","edge","corner","surface","other"]:
    c = bucket_counter.get(b,0)
    print(f"  {b:10s}: {c:8d}  {100*c/max(1,total_defects):5.1f}%")
print()
print("--- type by side (top 8 each) ---")
for s in side_counter:
    print(f"  [{s}]")
    for dt,c in type_by_side[s].most_common(8):
        print(f"      {c:7d}  {dt!r}")
print()
print("--- other array presence (cards with non-empty) ---")
for k,c in arr_presence.most_common():
    print(f"  {k}: {c}")
print()
print("--- dings_* summed counts (alt defect channel) ---")
for k,c in dings_sum.most_common():
    print(f"  {k}: {c}")
print()
print("--- grade distribution ---")
for g in sorted(grade_counter):
    print(f"  grade {g}: {grade_counter[g]}")
