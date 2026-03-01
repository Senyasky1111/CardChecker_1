"""Fill tcgplayer_id and tcgplayer_url for all EN cards using TCGCSV.com bulk data.

TCGCSV.com provides free daily dumps of TCGPlayer product data.
We download all Pokemon groups (sets), extract card products with their
productId and collector numbers, then match to our cards by name + number.

Usage:
    python scripts/fill_tcgplayer_ids.py [--download] [--fill] [--dry-run]

    --download   Download fresh data from TCGCSV (saved to data/tcgplayer/)
    --fill       Match and fill tcgplayer_id + tcgplayer_url in cards table
    --dry-run    Don't write to DB, just show stats
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import io
import time
from pathlib import Path
from urllib.parse import quote_plus

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.db import ensure_schema

TCGCSV_BASE = "https://tcgcsv.com/tcgplayer/3"
DATA_DIR = Path("data/tcgplayer")
GROUPS_FILE = DATA_DIR / "groups.json"
PRODUCTS_FILE = DATA_DIR / "all_products.json"


def download_tcgplayer_data():
    """Download all Pokemon TCG products from TCGCSV.com."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "CardChecker/1.0"

    # Step 1: Get all groups (sets)
    print("Downloading groups...")
    r = session.get(f"{TCGCSV_BASE}/groups", timeout=30)
    r.raise_for_status()
    groups = r.json()["results"]
    print(f"  Found {len(groups)} groups")

    with open(GROUPS_FILE, "w", encoding="utf-8") as f:
        json.dump(groups, f, indent=2, ensure_ascii=False)

    # Step 2: Download products for each group
    all_products = []
    for i, group in enumerate(groups):
        gid = group["groupId"]
        gname = group["name"]
        print(f"  [{i+1}/{len(groups)}] {gname} (groupId={gid})...", end=" ", flush=True)

        try:
            r = session.get(f"{TCGCSV_BASE}/{gid}/products", timeout=30)
            r.raise_for_status()
            products = r.json()["results"]

            # Extract only card-relevant fields
            for prod in products:
                # Get card number from extendedData
                number = None
                for ext in prod.get("extendedData", []):
                    if ext["name"] == "Number":
                        number = ext["value"]
                        break

                all_products.append({
                    "productId": prod["productId"],
                    "name": prod["name"],
                    "cleanName": prod.get("cleanName", prod["name"]),
                    "groupId": gid,
                    "groupName": gname,
                    "url": prod.get("url", ""),
                    "number": number,
                })

            print(f"{len(products)} products")
        except Exception as e:
            print(f"ERROR: {e}")

        # Gentle rate limiting
        time.sleep(0.3)

    print(f"\nTotal products downloaded: {len(all_products)}")

    with open(PRODUCTS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_products, f, indent=2, ensure_ascii=False)

    print(f"Saved to {PRODUCTS_FILE}")
    return all_products


def load_products() -> list[dict]:
    """Load previously downloaded products."""
    if not PRODUCTS_FILE.exists():
        print(f"ERROR: {PRODUCTS_FILE} not found. Run with --download first.")
        sys.exit(1)
    with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_name(name: str) -> str:
    """Normalize card name for matching."""
    n = name.lower().strip()
    # Remove diacritics and special chars
    n = n.replace("'", "'").replace("\u2019", "'").replace("\u2018", "'")
    n = n.replace("\u00e9", "e")  # é -> e
    n = n.replace("&", "and")
    # Remove parenthetical suffixes like (Reverse Holo)
    n = re.sub(r"\s*\(.*?\)\s*$", "", n)
    # Remove extra whitespace
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _parse_number(num_str: str | None) -> int | None:
    """Extract numeric collector number from TCGPlayer format like '013/198'."""
    if not num_str:
        return None
    # Handle "013/198" format
    m = re.match(r"^(\d+)", num_str.split("/")[0].strip())
    if m:
        return int(m.group(1))
    return None


def _build_tcgplayer_search_url(name: str, lang: str = "en") -> str:
    """Build TCGPlayer search URL as fallback."""
    clean = re.sub(r"\s*\[.*?\]", "", name)
    clean = re.sub(r"\s*\(.*?\)", "", clean).strip()
    if not clean:
        return ""

    if lang == "ja":
        return f"https://www.tcgplayer.com/search/pokemon-japanese/product?q={quote_plus(clean)}&view=grid"
    else:
        return f"https://www.tcgplayer.com/search/pokemon/product?q={quote_plus(clean)}&view=grid"


def fill_tcgplayer_ids(conn, products: list[dict], dry_run: bool = False):
    """Match TCGPlayer products to our cards and fill IDs + URLs."""

    # Ensure columns exist
    for col in ["tcgplayer_url"]:
        try:
            conn.execute(f"ALTER TABLE cards ADD COLUMN {col} TEXT DEFAULT ''")
            conn.commit()
            print(f"  Added {col} column")
        except Exception:
            pass

    # Build lookup index from TCGPlayer products: (normalized_name, number) -> product
    # Also build name-only index for fallback
    by_name_num = {}  # (name, number) -> product
    by_name = {}      # name -> [products]

    for prod in products:
        norm = _normalize_name(prod["name"])
        num = _parse_number(prod.get("number"))

        key = (norm, num)
        if key not in by_name_num:
            by_name_num[key] = prod

        if norm not in by_name:
            by_name[norm] = []
        by_name[norm].append(prod)

    print(f"  TCGPlayer index: {len(by_name_num)} (name,num) pairs, {len(by_name)} unique names")

    # Get all EN cards
    cards = conn.execute("""
        SELECT tcgdex_id, name, eng_name, collector_number, set_id, language,
               tcgplayer_id
        FROM cards WHERE language = 'en'
    """).fetchall()

    matched_id = 0
    matched_url = 0
    search_url = 0
    already_had = 0

    for card in cards:
        card_name = card["name"] or card["eng_name"] or ""
        card_norm = _normalize_name(card_name)
        card_num = card["collector_number"]
        existing_id = card["tcgplayer_id"]

        tcgplayer_id = existing_id
        tcgplayer_url = ""
        product = None

        if not tcgplayer_id:
            # Try exact match: name + number
            product = by_name_num.get((card_norm, card_num))

            if not product and card_num:
                # Try name-only match, pick the one with closest number
                candidates = by_name.get(card_norm, [])
                if len(candidates) == 1:
                    product = candidates[0]
                elif candidates:
                    # Multiple matches — try to find by number
                    for c in candidates:
                        c_num = _parse_number(c.get("number"))
                        if c_num == card_num:
                            product = c
                            break

            if product:
                tcgplayer_id = product["productId"]
                matched_id += 1
        else:
            already_had += 1

        # Build URL
        if tcgplayer_id:
            # Direct product URL
            if product and product.get("url"):
                tcgplayer_url = product["url"]
            else:
                tcgplayer_url = f"https://www.tcgplayer.com/product/{tcgplayer_id}"
            matched_url += 1
        else:
            # Search URL fallback
            tcgplayer_url = _build_tcgplayer_search_url(card_name)
            if tcgplayer_url:
                search_url += 1

        if not dry_run and (tcgplayer_id or tcgplayer_url):
            conn.execute("""
                UPDATE cards SET tcgplayer_id = ?, tcgplayer_url = ?
                WHERE tcgdex_id = ?
            """, (tcgplayer_id, tcgplayer_url, card["tcgdex_id"]))

    if not dry_run:
        conn.commit()

    total = len(cards)
    print(f"\n  === EN TCGPlayer Results ===")
    print(f"  Already had ID: {already_had}")
    print(f"  Newly matched:  {matched_id}")
    print(f"  Total with ID:  {already_had + matched_id}/{total} ({100*(already_had+matched_id)/total:.1f}%)")
    print(f"  Direct URLs:    {matched_url}/{total} ({100*matched_url/total:.1f}%)")
    print(f"  Search URLs:    {search_url}/{total} ({100*search_url/total:.1f}%)")
    print(f"  Total with URL: {matched_url + search_url}/{total} ({100*(matched_url+search_url)/total:.1f}%)")

    return already_had + matched_id, search_url, total


def fill_jp_tw_search_urls(conn, dry_run: bool = False):
    """Fill TCGPlayer search URLs for JP/TW cards (no product IDs available)."""
    for lang, label, search_lang in [("ja", "JP", "ja"), ("zh-tw", "TW", "en")]:
        cards = conn.execute("""
            SELECT tcgdex_id, name, eng_name FROM cards
            WHERE language = ? AND (tcgplayer_url IS NULL OR tcgplayer_url = '')
        """, (lang,)).fetchall()

        filled = 0
        for card in cards:
            name = card["eng_name"] or card["name"] or ""
            if not name:
                continue
            url = _build_tcgplayer_search_url(name, search_lang)
            if url and not dry_run:
                conn.execute("UPDATE cards SET tcgplayer_url = ? WHERE tcgdex_id = ?",
                             (url, card["tcgdex_id"]))
            if url:
                filled += 1

        if not dry_run:
            conn.commit()

        total = conn.execute("SELECT COUNT(*) FROM cards WHERE language = ?", (lang,)).fetchone()[0]
        print(f"  {label}: {filled} search URLs filled ({100*filled/total:.1f}%)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true", help="Download from TCGCSV")
    parser.add_argument("--fill", action="store_true", help="Fill IDs and URLs")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.download and not args.fill:
        args.download = True
        args.fill = True

    if args.download:
        products = download_tcgplayer_data()

    if args.fill:
        products = load_products()
        conn = ensure_schema()

        print("\n=== Filling TCGPlayer IDs (EN) ===")
        fill_tcgplayer_ids(conn, products, args.dry_run)

        print("\n=== Filling TCGPlayer search URLs (JP/TW) ===")
        fill_jp_tw_search_urls(conn, args.dry_run)

        # Final stats
        print("\n=== Final TCGPlayer Coverage ===")
        for lang, label in [("en", "EN"), ("ja", "JP"), ("zh-tw", "TW")]:
            total = conn.execute("SELECT COUNT(*) FROM cards WHERE language=?", (lang,)).fetchone()[0]
            has_id = conn.execute(
                "SELECT COUNT(*) FROM cards WHERE language=? AND tcgplayer_id IS NOT NULL AND tcgplayer_id != '' AND tcgplayer_id != 0",
                (lang,)).fetchone()[0]
            has_url = conn.execute(
                "SELECT COUNT(*) FROM cards WHERE language=? AND tcgplayer_url IS NOT NULL AND tcgplayer_url != ''",
                (lang,)).fetchone()[0]
            print(f"  {label}: ID {has_id}/{total} ({100*has_id/total:.1f}%) | URL {has_url}/{total} ({100*has_url/total:.1f}%)")

        conn.close()


if __name__ == "__main__":
    main()
