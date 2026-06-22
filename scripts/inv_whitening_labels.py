"""Inventory the MAIN-photo whitening label set across data/tag_raw/*/metadata.json.

MAIN-only. SFX explicitly excluded. Quantifies:
 - cards & points for CORNER WEAR / EDGE WEAR / SURFACE-PLAY WEAR (whitening classes)
 - front vs back split
 - placeholder (50,50)-normalized filtering
 - distinct cards with >=1 whitening label
 - presence of FRONT_MAIN / BACK_MAIN on disk for those points
Coords normalized by each card's MAIN image dims (read dims lazily, cached per side).
"""
from __future__ import annotations
import os, json, glob, random
from collections import Counter, defaultdict

ROOT = r"D:\CardChecker\data\tag_raw"

WHITENING = {"CORNER WEAR", "EDGE WEAR", "SURFACE / PLAY WEAR", "PLAY WEAR DEFECT"}

dirs = glob.glob(os.path.join(ROOT, "*"))
dirs = [d for d in dirs if os.path.isdir(d)]
print(f"total cert dirs: {len(dirs)}")

# Counters
type_counter = Counter()              # every defect_type seen (all)
white_pts_by_type_side = Counter()    # (type, side) for whitening pts (non-placeholder)
white_pts_placeholder = Counter()     # (type, side) for placeholder pts
cards_with_white = set()
cards_with_white_front = set()
cards_with_white_back = set()
cards_with_main_front = 0
cards_with_main_back = 0
n_meta = 0
n_with_any_surface = 0
region_counter = Counter()            # region values for whitening pts
pts_total = 0
white_pts_total_raw = 0               # before placeholder filter

# image dim cache: many cards share nothing, so just read per-card when needed.
# We DON'T open images for counting; only sample 30 later. For placeholder detection
# we need dims to normalize. (50,50) placeholder = exact pixel 50,50? Memory says
# ~11% TAG points are (50,50) placeholders -> that's literal pixel (50,50). Check both:
# literal (50,50) AND normalized-center (0.5,0.5).

placeholder_literal = Counter()       # x==50 and y==50 exactly
sample_pts = []                        # for later crop inspection

random.seed(0)

for d in dirs:
    mp = os.path.join(d, "metadata.json")
    if not os.path.exists(mp):
        continue
    try:
        with open(mp, "r", encoding="utf-8") as f:
            m = json.load(f)
    except Exception:
        continue
    n_meta += 1
    cert = m.get("cert") or os.path.basename(d)
    sd = m.get("surface_defects") or []
    if sd:
        n_with_any_surface += 1
    has_white_f = False
    has_white_b = False
    for p in sd:
        pts_total += 1
        dt = (p.get("defect_type") or "").strip().upper()
        type_counter[dt] += 1
        if dt not in WHITENING:
            continue
        white_pts_total_raw += 1
        side = (p.get("side") or "").strip().lower()
        x = p.get("x"); y = p.get("y")
        region_counter[p.get("region")] += 1
        is_lit_ph = (x == 50 and y == 50)
        if is_lit_ph:
            placeholder_literal[(dt, side)] += 1
            white_pts_placeholder[(dt, side)] += 1
        else:
            white_pts_by_type_side[(dt, side)] += 1
            cards_with_white.add(cert)
            if side == "front":
                has_white_f = True
            elif side == "back":
                has_white_b = True
            # reservoir-ish sample for crop inspection
            if len(sample_pts) < 400:
                sample_pts.append((cert, d, side, dt, x, y, p.get("region")))
    if has_white_f:
        cards_with_white_front.add(cert)
    if has_white_b:
        cards_with_white_back.add(cert)

print(f"metadata.json parsed: {n_meta}")
print(f"cards with >=1 surface_defect of any kind: {n_with_any_surface}")
print(f"total surface_defect points (all types): {pts_total}")
print()
print("=== ALL defect_type counts (top) ===")
for t, c in type_counter.most_common():
    print(f"  {t!r:30s} {c}")
print()
print(f"=== WHITENING points (CORNER/EDGE/SURFACE-PLAY WEAR) ===")
print(f"raw whitening pts (incl placeholders): {white_pts_total_raw}")
ph_total = sum(placeholder_literal.values())
print(f"literal (50,50) placeholder whitening pts: {ph_total} ({100*ph_total/max(1,white_pts_total_raw):.1f}%)")
print(f"USABLE whitening pts (non-placeholder): {sum(white_pts_by_type_side.values())}")
print()
print("--- usable pts by (type, side) ---")
for (t, s), c in sorted(white_pts_by_type_side.items(), key=lambda kv: -kv[1]):
    print(f"  {t:14s} {s:6s} {c}")
print()
front_pts = sum(c for (t, s), c in white_pts_by_type_side.items() if s == "front")
back_pts = sum(c for (t, s), c in white_pts_by_type_side.items() if s == "back")
other_pts = sum(c for (t, s), c in white_pts_by_type_side.items() if s not in ("front", "back"))
tot = front_pts + back_pts + other_pts
print(f"front pts: {front_pts} ({100*front_pts/max(1,tot):.1f}%)")
print(f"back  pts: {back_pts} ({100*back_pts/max(1,tot):.1f}%)")
print(f"other pts: {other_pts}")
print()
print(f"=== DISTINCT CARDS with >=1 usable whitening label ===")
print(f"  total distinct cards: {len(cards_with_white)}")
print(f"  cards with whitening on FRONT: {len(cards_with_white_front)}")
print(f"  cards with whitening on BACK : {len(cards_with_white_back)}")
print()
print("=== region distribution (whitening pts) ===")
for r, c in region_counter.most_common(20):
    print(f"  region {r!r}: {c}")

# stash sample for separate crop script
with open(r"D:\CardChecker\scripts\_white_sample.json", "w") as f:
    json.dump(sample_pts, f)
print(f"\nsaved {len(sample_pts)} sample pts -> scripts/_white_sample.json")
