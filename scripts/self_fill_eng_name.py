"""Self-fill eng_name: copy from other cards with the same JP/TW name.

Many Trainer cards and Energy cards appear in multiple JP sets.
If one copy has eng_name, we can fill all others with the same name.

Usage:
    python scripts/self_fill_eng_name.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.db import ensure_schema


def self_fill_eng_name(conn, lang: str, dry_run: bool = False) -> int:
    """Fill eng_name from other cards with the same native name."""
    label = "JP" if lang == "ja" else "TW"

    # Build name -> eng_name lookup from cards that have eng_name
    lookup = {}
    rows = conn.execute("""
        SELECT DISTINCT name, eng_name FROM cards
        WHERE language = ? AND eng_name IS NOT NULL AND eng_name != ''
    """, (lang,)).fetchall()
    for r in rows:
        lookup[r["name"]] = r["eng_name"]

    # Get cards without eng_name
    cards = conn.execute("""
        SELECT tcgdex_id, name FROM cards
        WHERE language = ? AND (eng_name IS NULL OR eng_name = '')
    """, (lang,)).fetchall()

    filled = 0
    for card in cards:
        eng = lookup.get(card["name"])
        if eng:
            if not dry_run:
                conn.execute("UPDATE cards SET eng_name = ? WHERE tcgdex_id = ?",
                             (eng, card["tcgdex_id"]))
            filled += 1

    if not dry_run:
        conn.commit()

    print(f"  {label}: {filled}/{len(cards)} eng_name self-filled")
    return filled


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = ensure_schema()

    print("=== Self-Fill eng_name ===\n")

    # Before
    for lang, label in [("ja", "JP"), ("zh-tw", "TW")]:
        total = conn.execute("SELECT COUNT(*) FROM cards WHERE language=?", (lang,)).fetchone()[0]
        no_eng = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND (eng_name IS NULL OR eng_name='')", (lang,)).fetchone()[0]
        print(f"  {label}: {total} total, {no_eng} without eng_name")

    print()
    jp_filled = self_fill_eng_name(conn, "ja", args.dry_run)
    tw_filled = self_fill_eng_name(conn, "zh-tw", args.dry_run)

    # Now run fill_cm_by_name_only for newly-named cards
    if jp_filled > 0 or tw_filled > 0:
        print("\n=== Fill CM IDs for newly-named cards ===")
        # Import from fill_cross_language
        from scripts.fill_cross_language import fill_cm_by_name_only
        jp_cm = fill_cm_by_name_only(conn, "ja", args.dry_run)
        tw_cm = fill_cm_by_name_only(conn, "zh-tw", args.dry_run)
        print(f"  JP CM IDs via name-only: {jp_cm}")
        print(f"  TW CM IDs via name-only: {tw_cm}")

    # After
    print("\n=== Results ===")
    for lang, label in [("en", "EN"), ("ja", "JP"), ("zh-tw", "TW")]:
        total = conn.execute("SELECT COUNT(*) FROM cards WHERE language=?", (lang,)).fetchone()[0]
        no_eng = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND (eng_name IS NULL OR eng_name='')", (lang,)).fetchone()[0]
        has_eng = total - no_eng
        has_cm = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND cm_id_product IS NOT NULL AND cm_id_product > 0", (lang,)).fetchone()[0]
        has_price = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND top_price_eur > 0", (lang,)).fetchone()[0]
        print(f"  {label}: eng_name={has_eng} ({100*has_eng/total:.1f}%) | CM={has_cm} ({100*has_cm/total:.1f}%) | Price={has_price} ({100*has_price/total:.1f}%)")

    conn.close()


if __name__ == "__main__":
    main()
