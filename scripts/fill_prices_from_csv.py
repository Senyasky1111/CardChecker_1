"""Fill missing prices and CM IDs from CardMarket CSV data.

Uses cards_with_prices.json (65,487 products with price data)
to fill gaps for cards that have CM IDs but no price data,
and to find CM IDs by name for cards without them.

Usage:
    python scripts/fill_prices_from_csv.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
import io
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.db import ensure_schema

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
NOW = datetime.now(timezone.utc).isoformat()


def load_csv_products() -> dict[int, dict]:
    """Load CardMarket products from cards_with_prices.json."""
    path = Path("data/cardmarket/cards_with_prices.json")
    if not path.exists():
        print("ERROR: data/cardmarket/cards_with_prices.json not found")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    products = data["cards"]
    print(f"Loaded {len(products)} CardMarket products")

    # Build lookup by id_product
    by_id = {}
    for p in products:
        by_id[p["id_product"]] = p

    return by_id


def fill_prices_by_cm_id(conn, cm_products: dict[int, dict], dry_run: bool = False) -> dict:
    """Fill top_price_eur for cards with CM ID but no price."""
    stats = {"en": 0, "ja": 0, "zh-tw": 0}

    for lang, label in [("en", "EN"), ("ja", "JP"), ("zh-tw", "TW")]:
        cards = conn.execute("""
            SELECT tcgdex_id, cm_id_product FROM cards
            WHERE language = ? AND cm_id_product IS NOT NULL AND cm_id_product > 0
            AND (top_price_eur IS NULL OR top_price_eur = 0)
        """, (lang,)).fetchall()

        filled = 0
        prices_saved = 0
        for card in cards:
            p = cm_products.get(card["cm_id_product"])
            if not p:
                continue

            trend = p.get("price_trend") or 0
            avg = p.get("price_avg") or 0
            low = p.get("price_low") or 0
            best_price = trend or avg or low
            if best_price <= 0:
                continue

            if not dry_run:
                # Update top_price_eur on the card
                conn.execute("""
                    UPDATE cards SET top_price_eur = ?, enriched_at = ?
                    WHERE tcgdex_id = ?
                """, (best_price, NOW, card["tcgdex_id"]))

                # Also save to prices_external for consistency
                conn.execute("""
                    INSERT OR REPLACE INTO prices_external
                    (tcgdex_id, source, marketplace, condition, country, currency,
                     price_avg, price_low, price_high, price_trend,
                     avg_7d, avg_30d,
                     snapshot_date, updated_at)
                    VALUES (?, 'cardmarket_csv', 'cardmarket', 'AGGREGATED', 'ALL', 'EUR',
                            ?, ?, NULL, ?,
                            ?, ?,
                            ?, ?)
                """, (
                    card["tcgdex_id"],
                    avg or None, low or None, str(trend) if trend else "",
                    p.get("price_avg7"), p.get("price_avg30"),
                    TODAY, NOW,
                ))
                prices_saved += 1

                # If has foil price, save that too
                foil_trend = p.get("price_foil_trend") or 0
                foil_low = p.get("price_foil_low") or 0
                if foil_trend > 0 or foil_low > 0:
                    conn.execute("""
                        INSERT OR REPLACE INTO prices_external
                        (tcgdex_id, source, marketplace, condition, country, currency,
                         price_avg, price_low, price_trend,
                         snapshot_date, updated_at)
                        VALUES (?, 'cardmarket_csv', 'cardmarket', 'FOIL', 'ALL', 'EUR',
                                NULL, ?, ?,
                                ?, ?)
                    """, (
                        card["tcgdex_id"],
                        foil_low or None, str(foil_trend) if foil_trend else "",
                        TODAY, NOW,
                    ))
                    prices_saved += 1

            filled += 1

        stats[lang] = filled
        print(f"  {label}: {filled}/{len(cards)} prices filled from CSV ({prices_saved} price rows)")

    if not dry_run:
        conn.commit()

    return stats


def fill_cm_ids_by_name(conn, cm_products: dict[int, dict], dry_run: bool = False) -> int:
    """Find CM IDs for EN cards without them by matching product name."""
    # Build name -> products lookup
    by_name = {}
    for p in cm_products.values():
        name_lower = p["name"].lower().strip()
        if name_lower not in by_name:
            by_name[name_lower] = []
        by_name[name_lower].append(p)

    # Also build name+expansion lookup for disambiguation
    by_name_exp = {}
    for p in cm_products.values():
        key = (p["name"].lower().strip(), p.get("expansion_id", 0))
        by_name_exp[key] = p

    cards = conn.execute("""
        SELECT tcgdex_id, name, eng_name, set_id FROM cards
        WHERE language = 'en' AND (cm_id_product IS NULL OR cm_id_product = 0)
    """).fetchall()

    filled = 0
    for card in cards:
        name = (card["name"] or "").lower().strip()
        if not name:
            continue

        matches = by_name.get(name, [])
        if not matches:
            continue

        if len(matches) == 1:
            cm_id = matches[0]["id_product"]
        else:
            # Multiple matches - just take the first one (newest)
            cm_id = max(matches, key=lambda x: x["id_product"])["id_product"]

        if not dry_run:
            conn.execute("UPDATE cards SET cm_id_product = ? WHERE tcgdex_id = ?",
                         (cm_id, card["tcgdex_id"]))

            # Also set price
            p = cm_products[cm_id]
            trend = p.get("price_trend") or 0
            avg = p.get("price_avg") or 0
            best = trend or avg
            if best > 0:
                conn.execute("UPDATE cards SET top_price_eur = ?, enriched_at = ? WHERE tcgdex_id = ?",
                             (best, NOW, card["tcgdex_id"]))

        filled += 1

    if not dry_run:
        conn.commit()

    return filled


def main():
    parser = argparse.ArgumentParser(description="Fill prices from CardMarket CSV")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = ensure_schema()
    cm_products = load_csv_products()

    print("\n=== Step 1: Fill prices for cards with CM ID but no price ===")
    stats = fill_prices_by_cm_id(conn, cm_products, args.dry_run)

    print("\n=== Step 2: Find CM IDs for EN cards by name ===")
    en_found = fill_cm_ids_by_name(conn, cm_products, args.dry_run)
    print(f"  EN cards matched by name: {en_found}")

    # Final stats
    print("\n=== Final Coverage ===")
    for lang_name, lang_code in [("EN", "en"), ("JP", "ja"), ("TW", "zh-tw")]:
        total = conn.execute("SELECT COUNT(*) FROM cards WHERE language=?", (lang_code,)).fetchone()[0]
        has_cm = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND cm_id_product IS NOT NULL AND cm_id_product > 0", (lang_code,)).fetchone()[0]
        has_price = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND top_price_eur > 0", (lang_code,)).fetchone()[0]
        enriched = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND enriched_at IS NOT NULL AND enriched_at != ''", (lang_code,)).fetchone()[0]
        print(f"  {lang_name}: {total} | CM: {has_cm} ({100*has_cm/total:.1f}%) | Price: {has_price} ({100*has_price/total:.1f}%) | Enriched: {enriched} ({100*enriched/total:.1f}%)")

    total = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    total_price = conn.execute("SELECT COUNT(*) FROM cards WHERE top_price_eur > 0").fetchone()[0]
    total_pe = conn.execute("SELECT COUNT(*) FROM prices_external").fetchone()[0]
    print(f"\n  Total: {total_price}/{total} ({100*total_price/total:.1f}%) have prices | {total_pe} price rows")

    conn.close()


if __name__ == "__main__":
    main()
