"""
Fill missing eng_name and cm_id_product for JP/TW cards
by cross-referencing with EN counterparts.

Strategy:
1. Discover JP->EN set mapping using multiple methods:
   a. Cards that already have eng_name (name+number match)
   b. Set abbreviation/name matching
   c. TW->JP prefix stripping + JP->EN chain
2. Fill eng_name by matching collector_number within mapped sets
3. Inherit cm_id_product from EN cards
4. Direct name+number CM ID fill for remaining cards

Usage:
    python scripts/fill_cross_language.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.db import ensure_schema


def _normalize_code(s: str) -> str:
    """Normalize set code for matching."""
    return (s or "").strip().lower().replace("-", "").replace(".", "").replace(" ", "").replace("_", "")


def discover_jp_en_set_mapping(conn) -> dict[str, str]:
    """Discover JP->EN set mapping using multiple strategies."""

    # Strategy 1: eng_name-based mapping (most reliable)
    rows = conn.execute("""
        SELECT ja.set_id as ja_set, en.set_id as en_set, COUNT(*) as cnt
        FROM cards ja
        JOIN cards en ON en.language = 'en'
            AND en.collector_number = ja.collector_number
            AND LOWER(TRIM(en.name)) = LOWER(TRIM(ja.eng_name))
        WHERE ja.language = 'ja'
            AND ja.eng_name IS NOT NULL AND ja.eng_name != ''
            AND ja.collector_number IS NOT NULL
        GROUP BY ja.set_id, en.set_id
        HAVING cnt >= 2
        ORDER BY ja.set_id, cnt DESC
    """).fetchall()

    jp_candidates = defaultdict(list)
    for r in rows:
        jp_candidates[r["ja_set"]].append((r["en_set"], r["cnt"]))

    jp_en_map = {}
    for jp_set, candidates in jp_candidates.items():
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_en, best_cnt = candidates[0]
        if len(candidates) > 1:
            second_cnt = candidates[1][1]
            if best_cnt < second_cnt * 1.5:
                continue
        jp_en_map[jp_set] = best_en

    engname_count = len(jp_en_map)

    # Strategy 2: abbreviation/name-based matching
    en_sets = conn.execute("SELECT set_id, abbreviation, name FROM sets WHERE language = 'en'").fetchall()
    jp_sets = conn.execute("SELECT set_id, abbreviation, name FROM sets WHERE language = 'ja'").fetchall()

    en_by_code = {}
    for s in en_sets:
        n = _normalize_code(s["abbreviation"])
        if n:
            en_by_code[n] = s["set_id"]
        n2 = _normalize_code(s["name"])
        if n2 and n2 not in en_by_code:
            en_by_code[n2] = s["set_id"]

    abbr_added = 0
    for s in jp_sets:
        jp_id = s["set_id"]
        if jp_id in jp_en_map:
            continue  # already mapped

        jp_abbr = _normalize_code(s["abbreviation"])
        jp_name = _normalize_code(s["name"])

        en_match = en_by_code.get(jp_abbr) or en_by_code.get(jp_name)

        # Partial matching (e.g. sv8a matches sv08.5 -> sv085)
        if not en_match and jp_abbr:
            for en_code, en_id in en_by_code.items():
                if len(jp_abbr) >= 3 and len(en_code) >= 3:
                    if jp_abbr in en_code or en_code in jp_abbr:
                        en_match = en_id
                        break

        if en_match:
            jp_en_map[jp_id] = en_match
            abbr_added += 1

    print(f"  eng_name-based: {engname_count} | abbreviation-based: +{abbr_added} | total: {len(jp_en_map)}")
    return jp_en_map


def discover_tw_jp_set_mapping(conn) -> dict[str, str]:
    """Discover TW->JP set mapping by stripping tw- prefix."""
    tw_sets = conn.execute("SELECT set_id FROM sets WHERE language='zh-tw'").fetchall()
    jp_set_ids = set(r["set_id"] for r in conn.execute("SELECT set_id FROM sets WHERE language='ja'").fetchall())

    tw_jp_map = {}
    for tw in tw_sets:
        tw_id = tw["set_id"]
        jp_candidate = tw_id.replace("tw-", "")
        if jp_candidate in jp_set_ids:
            tw_jp_map[tw_id] = jp_candidate

    return tw_jp_map


def discover_tw_en_direct(conn) -> dict[str, str]:
    """Direct TW->EN mapping via abbreviation/name."""
    en_sets = conn.execute("SELECT set_id, abbreviation, name FROM sets WHERE language = 'en'").fetchall()
    tw_sets = conn.execute("SELECT set_id, abbreviation, name FROM sets WHERE language = 'zh-tw'").fetchall()

    en_by_code = {}
    for s in en_sets:
        n = _normalize_code(s["abbreviation"])
        if n:
            en_by_code[n] = s["set_id"]
        n2 = _normalize_code(s["name"])
        if n2 and n2 not in en_by_code:
            en_by_code[n2] = s["set_id"]

    tw_en_map = {}
    for s in tw_sets:
        tw_id = s["set_id"]
        # Strip tw- prefix for matching
        raw_id = tw_id.replace("tw-", "")
        tw_abbr = _normalize_code(s["abbreviation"] or raw_id)
        tw_name = _normalize_code(s["name"])

        en_match = en_by_code.get(tw_abbr) or en_by_code.get(tw_name)

        if not en_match and tw_abbr:
            for en_code, en_id in en_by_code.items():
                if len(tw_abbr) >= 3 and len(en_code) >= 3:
                    if tw_abbr in en_code or en_code in tw_abbr:
                        en_match = en_id
                        break

        if en_match:
            tw_en_map[tw_id] = en_match

    return tw_en_map


def fill_eng_name(conn, lang: str, lang_en_map: dict[str, str], dry_run: bool = False) -> int:
    """Fill eng_name for cards by matching to EN cards via set mapping."""
    lang_label = "JP" if lang == "ja" else "TW"
    filled = 0

    # Get cards without eng_name in mapped sets
    mapped_set_ids = list(lang_en_map.keys())
    if not mapped_set_ids:
        print(f"  No set mappings for {lang_label}")
        return 0

    placeholders = ",".join("?" * len(mapped_set_ids))
    cards = conn.execute(f"""
        SELECT tcgdex_id, name, set_id, collector_number
        FROM cards
        WHERE language = ? AND (eng_name IS NULL OR eng_name = '')
        AND collector_number IS NOT NULL
        AND set_id IN ({placeholders})
    """, [lang] + mapped_set_ids).fetchall()

    print(f"  {lang_label} cards without eng_name in mapped sets: {len(cards)}")

    for card in cards:
        en_set = lang_en_map.get(card["set_id"])
        if not en_set:
            continue

        # Find EN card with same collector_number
        en_card = conn.execute("""
            SELECT name, cm_id_product FROM cards
            WHERE language = 'en' AND set_id = ? AND collector_number = ?
            LIMIT 1
        """, (en_set, card["collector_number"])).fetchone()

        if en_card and en_card["name"]:
            if not dry_run:
                conn.execute("""
                    UPDATE cards SET eng_name = ?
                    WHERE tcgdex_id = ?
                """, (en_card["name"], card["tcgdex_id"]))
            filled += 1

    if not dry_run:
        conn.commit()

    return filled


def inherit_cm_ids(conn, lang: str, lang_en_map: dict[str, str], dry_run: bool = False) -> int:
    """Inherit cm_id_product from EN counterparts."""
    lang_label = "JP" if lang == "ja" else "TW"
    inherited = 0

    mapped_set_ids = list(lang_en_map.keys())
    if not mapped_set_ids:
        return 0

    placeholders = ",".join("?" * len(mapped_set_ids))
    cards = conn.execute(f"""
        SELECT tcgdex_id, set_id, collector_number
        FROM cards
        WHERE language = ? AND (cm_id_product IS NULL OR cm_id_product = 0)
        AND collector_number IS NOT NULL
        AND set_id IN ({placeholders})
    """, [lang] + mapped_set_ids).fetchall()

    print(f"  {lang_label} cards without CM ID in mapped sets: {len(cards)}")

    for card in cards:
        en_set = lang_en_map.get(card["set_id"])
        if not en_set:
            continue

        en_card = conn.execute("""
            SELECT cm_id_product FROM cards
            WHERE language = 'en' AND set_id = ? AND collector_number = ?
            AND cm_id_product IS NOT NULL AND cm_id_product > 0
            LIMIT 1
        """, (en_set, card["collector_number"])).fetchone()

        if en_card:
            if not dry_run:
                conn.execute("""
                    UPDATE cards SET cm_id_product = ?
                    WHERE tcgdex_id = ?
                """, (en_card["cm_id_product"], card["tcgdex_id"]))
            inherited += 1

    if not dry_run:
        conn.commit()

    return inherited


def fill_from_en_direct(conn, lang: str, dry_run: bool = False) -> int:
    """Direct fill: for cards WITH eng_name but no CM ID, find EN card by name + number."""
    filled = 0

    cards = conn.execute("""
        SELECT tcgdex_id, eng_name, collector_number
        FROM cards
        WHERE language = ?
        AND (cm_id_product IS NULL OR cm_id_product = 0)
        AND eng_name IS NOT NULL AND eng_name != ''
        AND collector_number IS NOT NULL
    """, (lang,)).fetchall()

    for card in cards:
        en_card = conn.execute("""
            SELECT cm_id_product FROM cards
            WHERE language = 'en'
            AND LOWER(TRIM(name)) = LOWER(TRIM(?))
            AND collector_number = ?
            AND cm_id_product IS NOT NULL AND cm_id_product > 0
            LIMIT 1
        """, (card["eng_name"], card["collector_number"])).fetchone()

        if en_card:
            if not dry_run:
                conn.execute("""
                    UPDATE cards SET cm_id_product = ?
                    WHERE tcgdex_id = ?
                """, (en_card["cm_id_product"], card["tcgdex_id"]))
            filled += 1

    if not dry_run:
        conn.commit()

    return filled


def fill_cm_by_name_only(conn, lang: str, dry_run: bool = False) -> int:
    """Fill cm_id_product by matching eng_name to ANY EN card (ignoring collector_number).

    This handles compilation sets (SV8a, S12a, MC, etc.) where JP collector_numbers
    don't match EN collector_numbers because cards come from multiple EN sets.

    Matching strategy:
    - If eng_name matches exactly ONE EN card -> inherit its cm_id_product
    - If eng_name matches multiple EN cards -> pick the one with highest cm_id_product
      (newer/more recent product)
    """
    filled = 0

    cards = conn.execute("""
        SELECT tcgdex_id, eng_name, collector_number
        FROM cards
        WHERE language = ?
        AND (cm_id_product IS NULL OR cm_id_product = 0)
        AND eng_name IS NOT NULL AND eng_name != ''
    """, (lang,)).fetchall()

    lang_label = "JP" if lang == "ja" else "TW"
    print(f"  {lang_label} cards with eng_name but no CM ID: {len(cards)}")

    for card in cards:
        # Find EN cards with same name (case-insensitive)
        en_cards = conn.execute("""
            SELECT cm_id_product, collector_number, set_id FROM cards
            WHERE language = 'en'
            AND LOWER(TRIM(name)) = LOWER(TRIM(?))
            AND cm_id_product IS NOT NULL AND cm_id_product > 0
            ORDER BY cm_id_product DESC
        """, (card["eng_name"],)).fetchall()

        if not en_cards:
            continue

        # If only one match, use it
        if len(en_cards) == 1:
            cm_id = en_cards[0]["cm_id_product"]
        else:
            # Multiple matches - try to find by collector_number first
            best = None
            for ec in en_cards:
                if ec["collector_number"] == card["collector_number"]:
                    best = ec
                    break
            if best:
                cm_id = best["cm_id_product"]
            else:
                # Just use the one with highest cm_id_product (most recent)
                cm_id = en_cards[0]["cm_id_product"]

        if not dry_run:
            conn.execute("""
                UPDATE cards SET cm_id_product = ?
                WHERE tcgdex_id = ?
            """, (cm_id, card["tcgdex_id"]))
        filled += 1

    if not dry_run:
        conn.commit()

    return filled


def main():
    parser = argparse.ArgumentParser(description="Fill missing eng_name and CM IDs cross-language")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = ensure_schema()

    print("=== Cross-Language Fill ===\n")

    # Stats before
    for lang_name, lang_code in [("EN", "en"), ("JP", "ja"), ("TW", "zh-tw")]:
        total = conn.execute("SELECT COUNT(*) FROM cards WHERE language=?", (lang_code,)).fetchone()[0]
        no_eng = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND (eng_name IS NULL OR eng_name='')", (lang_code,)).fetchone()[0]
        no_cm = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND (cm_id_product IS NULL OR cm_id_product=0)", (lang_code,)).fetchone()[0]
        print(f"  {lang_name}: {total} | no eng_name: {no_eng} | no CM: {no_cm}")

    # Step 1: Discover set mappings
    print("\n--- Step 1: Discover set mappings ---")
    jp_en_map = discover_jp_en_set_mapping(conn)
    tw_jp_map = discover_tw_jp_set_mapping(conn)

    # Chain TW -> JP -> EN
    tw_en_chain = {}
    for tw_id, jp_id in tw_jp_map.items():
        if jp_id in jp_en_map:
            tw_en_chain[tw_id] = jp_en_map[jp_id]

    # Also try direct TW->EN matching
    tw_en_direct = discover_tw_en_direct(conn)

    # Merge: chain mappings + direct (chain takes priority as more reliable)
    tw_en_map = {**tw_en_direct}
    tw_en_map.update(tw_en_chain)  # chain overwrites direct if both exist

    print(f"  JP->EN set mappings: {len(jp_en_map)}")
    print(f"  TW->JP set mappings: {len(tw_jp_map)}")
    print(f"  TW->EN chain mappings: {len(tw_en_chain)}")
    print(f"  TW->EN direct mappings: {len(tw_en_direct)}")
    print(f"  TW->EN total (merged): {len(tw_en_map)}")

    # Step 2: Fill eng_name
    print("\n--- Step 2: Fill eng_name ---")
    jp_filled = fill_eng_name(conn, "ja", jp_en_map, args.dry_run)
    tw_filled = fill_eng_name(conn, "zh-tw", tw_en_map, args.dry_run)
    print(f"  JP eng_name filled: {jp_filled}")
    print(f"  TW eng_name filled: {tw_filled}")

    # Step 3: Inherit CM IDs via set mapping
    print("\n--- Step 3: Inherit CM IDs via set mapping ---")
    jp_cm = inherit_cm_ids(conn, "ja", jp_en_map, args.dry_run)
    tw_cm = inherit_cm_ids(conn, "zh-tw", tw_en_map, args.dry_run)
    print(f"  JP CM IDs inherited: {jp_cm}")
    print(f"  TW CM IDs inherited: {tw_cm}")

    # Step 4: Direct name+number CM ID fill
    print("\n--- Step 4: Direct name+number CM ID fill ---")
    jp_direct = fill_from_en_direct(conn, "ja", args.dry_run)
    tw_direct = fill_from_en_direct(conn, "zh-tw", args.dry_run)
    print(f"  JP CM IDs via name+number: {jp_direct}")
    print(f"  TW CM IDs via name+number: {tw_direct}")

    # Step 5: Name-only CM ID fill (for compilation sets where collector_number differs)
    print("\n--- Step 5: Name-only CM ID fill (compilation sets) ---")
    jp_name = fill_cm_by_name_only(conn, "ja", args.dry_run)
    tw_name = fill_cm_by_name_only(conn, "zh-tw", args.dry_run)
    print(f"  JP CM IDs via name-only: {jp_name}")
    print(f"  TW CM IDs via name-only: {tw_name}")

    # Stats after
    print("\n=== Results ===")
    for lang_name, lang_code in [("EN", "en"), ("JP", "ja"), ("TW", "zh-tw")]:
        total = conn.execute("SELECT COUNT(*) FROM cards WHERE language=?", (lang_code,)).fetchone()[0]
        no_eng = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND (eng_name IS NULL OR eng_name='')", (lang_code,)).fetchone()[0]
        has_eng = total - no_eng
        no_cm = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND (cm_id_product IS NULL OR cm_id_product=0)", (lang_code,)).fetchone()[0]
        has_cm = total - no_cm
        print(f"  {lang_name}: {total} | eng_name: {has_eng} ({100*has_eng/total:.1f}%) | CM: {has_cm} ({100*has_cm/total:.1f}%)")

    conn.close()


if __name__ == "__main__":
    main()
