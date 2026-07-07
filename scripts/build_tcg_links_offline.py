from __future__ import annotations

"""
Offline TCGplayer link builder for JP cards, using the free TCGCSV category-85
(Pokemon Japan) catalog downloaded by scripts/download_tcgcsv_jp.py.

Same idea as the CardMarket offline join: TCGCSV gives each JP product a
productId + collector Number (extendedData) + its group (set). The group's
abbreviation is the JP set code (m2a, sv4a, ...), so we resolve the exact
tcgplayer_id by an offline join on (set_code, number). This unlocks JP/TW US
pricing too (PokeTrace is keyed by tcgplayer_id).

DRY-RUN: writes scripts/_tcg_writes.json (tcgplayer_id + product url) + scorecard.
Nothing touches prod. Name-agreement gate (eng_name vs product cleanName) guards
against set-code collisions; matched-but-mismatch rows are reported, not written.

Usage:
  ./venv/Scripts/python.exe scripts/build_tcg_links_offline.py
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUPS = ROOT / "data" / "tcgplayer" / "jp_groups.json"
PRODUCTS = ROOT / "data" / "tcgplayer" / "jp_products.json"
CARDS = ROOT / "scripts" / "_prod_cards_eng.json"
OUT = ROOT / "scripts" / "_tcg_writes.json"

_suffix = re.compile(r"\b(ex|EX|GX|V|VMAX|VSTAR|Prime|BREAK|Lv\.?\d+)\b")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def strip_pref(s: str) -> str:
    return re.sub(r"^(tw-|jp-)", "", s or "")


def pokebase(name: str) -> str:
    name = re.sub(r"\([^)]*\)", "", name or "").replace("&amp;", "&")
    # drop trailing " - NNN/NNN" style and set words after a dash
    name = name.split(" - ")[0]
    return norm(_suffix.sub("", name))


def parse_number(num_str):
    if not num_str:
        return None
    m = re.match(r"^0*(\d+)", str(num_str).split("/")[0].strip())
    return int(m.group(1)) if m else None


def group_code(g: dict) -> str:
    """Prefer abbreviation; else the token before the first ':' in the name."""
    ab = norm(g.get("abbreviation", ""))
    if ab:
        return ab
    name = g.get("name", "")
    head = name.split(":", 1)[0].strip()
    return norm(head)


def name_agrees(eng: str, base: str) -> bool:
    a = norm(eng)
    if not a or not base:
        return False
    return a in base or base in a or (len(a) >= 4 and a[:4] == base[:4])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", default="ja,zh-tw")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    groups = json.loads(GROUPS.read_text(encoding="utf-8"))
    gcode = {g["groupId"]: group_code(g) for g in groups}
    products = json.loads(PRODUCTS.read_text(encoding="utf-8"))

    idx = defaultdict(list)  # (code, num) -> [(pid, url, base)]
    for p in products:
        code = gcode.get(p["groupId"])
        num = parse_number(p.get("number"))
        if not code or num is None:
            continue
        idx[(code, num)].append(
            (p["productId"], p.get("url", ""), pokebase(p.get("cleanName") or p.get("name", ""))))

    cards = json.loads(CARDS.read_text(encoding="utf-8"))
    langs = [x.strip() for x in args.langs.split(",") if x.strip()]

    proposals = []
    stats = defaultdict(lambda: defaultdict(int))
    mism = []
    for lang in langs:
        for tcgdex_id, set_id, cnum, eng, cm_id, cm_slug in cards[lang]:
            s = stats[lang]
            s["total"] += 1
            try:
                num = int(cnum)
            except (TypeError, ValueError):
                s["no_number"] += 1
                continue
            code = norm(strip_pref(set_id))
            cands = idx.get((code, num))
            if not cands:
                s["miss"] += 1
                continue
            s["match"] += 1
            agreeing = [c for c in cands if name_agrees(eng, c[2])]
            chosen = (agreeing or cands)[0]
            pid, url, base = chosen
            if agreeing:
                s["name_ok"] += 1
            else:
                s["name_mismatch"] += 1
                if len(mism) < 30:
                    mism.append((lang, set_id, cnum, eng, base))
            proposals.append({
                "tcgdex_id": tcgdex_id, "language": lang, "set_id": set_id,
                "collector_number": cnum, "eng_name": eng,
                "tcgplayer_id": pid,
                "tcgplayer_url": url or f"https://www.tcgplayer.com/product/{pid}",
                "name_ok": bool(agreeing), "ambiguous": len(cands) > 1,
            })

    Path(args.out).write_text(
        json.dumps(proposals, ensure_ascii=False, indent=2), encoding="utf-8")

    print("================ TCGPLAYER OFFLINE (cat 85) — DRY RUN ================")
    for lang in langs:
        s = stats[lang]
        t = s["total"] or 1
        print(f"\n[{lang}] {s['total']} cards")
        print(f"  matched          {s['match']:5d} ({100*s['match']//t}%)  "
              f"[ambiguous {sum(1 for p in proposals if p['language']==lang and p['ambiguous'])}]")
        print(f"    name agrees    {s['name_ok']:5d}   mismatch {s['name_mismatch']}")
        print(f"  miss             {s['miss']:5d}   no int number {s['no_number']}")
    print(f"\nproposals: {args.out}  ({len(proposals)} rows)")
    if mism:
        print("\n--- sample name-mismatches ---")
        for lang, sid, cnum, eng, base in mism[:15]:
            print(f"  {lang:5s} {sid:8s}#{cnum:<4} ours={eng!r:20} TCG={base!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
