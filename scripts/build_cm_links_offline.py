from __future__ import annotations

"""
Offline CardMarket link builder for JP/TW cards.

Key insight (validated 2026-07-06): the local CardMarket product catalog
(`data/cardmarket/_cm_products_all.json`, 58k products, 741 expansions incl. all
Japanese sets) encodes the JP set-code + collector number directly in each
product name/slug, e.g.:

    name  = "Mew ex  (sv4a 076)"
    slug  = "Shiny-Treasure-ex/Mew-ex-V1-sv4a076"

So we can resolve the *exact* CardMarket product for a JP/TW card by an offline
join on (set_code, collector_number) — no Serper / no scraping. This:
  * FIXES the wrong cm_id_product (the JA 66% / TW 80% shared-id bug), and
  * FILLS the empty cm_url_slug (clean canonical /Singles/{slug} URL).

Coverage (stale Feb catalog): JA ~65%, TW ~60% at high precision. Residual =
old DP/BW/XY sets (CM stores them by name+level, no number), promos (number-less),
and TW A-codes (need a TW->JP alias). Those are handled separately.

DRY-RUN by default: writes a proposal JSON + prints a scorecard. Nothing touches
prod until you run the companion apply step with an explicit flag.

Usage:
  ./venv/Scripts/python.exe scripts/build_cm_links_offline.py            # dry-run
  ./venv/Scripts/python.exe scripts/build_cm_links_offline.py --out ...  # custom out
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "cardmarket" / "_cm_products_all.json"
CARDS = ROOT / "scripts" / "_prod_cards_eng.json"   # dumped from prod: {lang: [rows]}
OUT_DEFAULT = ROOT / "scripts" / "_cm_offline_proposed.json"

CM_BASE = "https://www.cardmarket.com"
_paren = re.compile(r"\(([^)]*)\)")
# require a SPACE between code and number so "(DP1)" is NOT split into ("dp", 1)
_code_num = re.compile(r"^([A-Za-z][A-Za-z0-9-]*?)\s+0*(\d+)$")
_suffix = re.compile(r"\b(ex|EX|GX|V|VMAX|VSTAR|Prime|BREAK|Lv\.?\d+)\b")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def strip_pref(s: str) -> str:
    return re.sub(r"^(tw-|jp-)", "", s or "")


def pokebase(name: str) -> str:
    name = re.sub(r"\([^)]*\)", "", name or "").replace("&amp;", "&")
    return norm(_suffix.sub("", name))


def build_index(catalog: dict) -> dict:
    """(code, num) -> list of (pid:int, slug, expansion, pokebase)."""
    idx: dict = defaultdict(list)
    for pid, p in catalog["products"].items():
        m = _paren.findall(p.get("name", "") or "")
        if not m:
            continue
        mm = _code_num.match(m[-1].strip())
        if not mm:
            continue
        code = norm(mm.group(1))
        if not code:
            continue
        idx[(code, int(mm.group(2)))].append(
            (int(pid), p.get("slug", ""), p.get("expansion", ""),
             pokebase(p.get("name", "")))
        )
    return idx


def name_agrees(eng: str, cm_base: str) -> bool:
    a = norm(eng)
    if not a or not cm_base:
        return False
    return a in cm_base or cm_base in a or (len(a) >= 4 and a[:4] == cm_base[:4])


def choose(cands: list, eng: str) -> tuple:
    """Pick best candidate: prefer name-agreement, then shortest slug (base print)."""
    agreeing = [c for c in cands if name_agrees(eng, c[3])]
    pool = agreeing or cands
    return min(pool, key=lambda c: len(c[1] or "")), bool(agreeing)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--langs", default="ja,zh-tw")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    idx = build_index(catalog)
    cards = json.loads(CARDS.read_text(encoding="utf-8"))
    langs = [x.strip() for x in args.langs.split(",") if x.strip()]

    proposals = []
    stats = defaultdict(lambda: defaultdict(int))
    mismatches = []
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
            chosen, agreed = choose(cands, eng)
            pid, slug, expansion, cm_base = chosen
            if len(cands) > 1:
                s["ambiguous"] += 1
            if agreed:
                s["name_ok"] += 1
            else:
                s["name_mismatch"] += 1
                if len(mismatches) < 40:
                    mismatches.append((lang, set_id, cnum, eng, cm_base, expansion))
            if cm_id and pid != cm_id:
                s["fix_cmid"] += 1
            if not (cm_slug or "").strip():
                s["fill_slug"] += 1
            proposals.append({
                "tcgdex_id": tcgdex_id, "language": lang, "set_id": set_id,
                "collector_number": cnum, "eng_name": eng,
                "old_cm_id": cm_id, "new_cm_id": pid,
                "cm_url_slug": slug, "expansion": expansion,
                "name_ok": agreed, "ambiguous": len(cands) > 1,
                "url": f"{CM_BASE}/en/Pokemon/Products/Singles/{slug}",
            })

    Path(args.out).write_text(
        json.dumps(proposals, ensure_ascii=False, indent=2), encoding="utf-8")

    print("================ CM OFFLINE MATCH — DRY RUN ================")
    for lang in langs:
        s = stats[lang]
        t = s["total"] or 1
        print(f"\n[{lang}] {s['total']} cards")
        print(f"  matched            {s['match']:5d} ({100*s['match']//t}%)"
              f"   [ambiguous {s['ambiguous']}]")
        print(f"    name agrees      {s['name_ok']:5d}"
              f"   name mismatch {s['name_mismatch']}")
        print(f"  would FIX cm_id    {s['fix_cmid']:5d}")
        print(f"  would FILL slug    {s['fill_slug']:5d}")
        print(f"  miss (no product)  {s['miss']:5d}"
              f"   no int number {s['no_number']}")
    print(f"\nProposals written: {args.out}  ({len(proposals)} rows)")
    if mismatches:
        print("\n--- sample name-mismatches (review) ---")
        for lang, sid, cnum, eng, cmb, exp in mismatches[:20]:
            print(f"  {lang:5s} {sid:8s}#{cnum:<4} ours={eng!r:20} CM={cmb!r:16} [{exp}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
