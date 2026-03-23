"""Scrape PriceCharting to discover ALL available JP and TW set slugs,
then auto-map them to our DB set_ids.

Strategy:
1. Fetch the category page /category/pokemon-cards
2. Extract all /console/pokemon-japanese-* and /console/pokemon-chinese-* links
3. For each PC set, fetch the first page and grab a few card names+numbers
4. Match those cards to our DB to find the set_id
5. Output new mappings that can be added to build_pricecharting_map.py

Usage:
    python scripts/scrape_pc_sets.py [--update]  # --update writes to build_pricecharting_map.py
"""

from __future__ import annotations
import io
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    sys.stdout = io.TextIOWrapper(
        open(sys.stdout.fileno(), "wb", closefd=False),
        encoding="utf-8", errors="replace", line_buffering=True,
    )
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PC_BASE = "https://www.pricecharting.com"
DB_PATH = Path("data/cards.db")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
}


def fetch_category_sets(session: requests.Session) -> dict[str, list[tuple[str, str]]]:
    """Fetch all JP and Chinese set links from PriceCharting category page."""
    url = f"{PC_BASE}/category/pokemon-cards"
    r = session.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    sets: dict[str, list[tuple[str, str]]] = {"ja": [], "zh-tw": []}

    for a in soup.find_all("a", href=True):
        href = a["href"]
        name = a.get_text(strip=True)
        if "/console/pokemon-japanese-" in href:
            slug = href.split("/console/pokemon-japanese-")[-1]
            slug = slug.rstrip("/")
            sets["ja"].append((slug, name))
        elif "/console/pokemon-chinese-" in href:
            slug = href.split("/console/pokemon-chinese-")[-1]
            slug = slug.rstrip("/")
            sets["zh-tw"].append((slug, name))

    return sets


def fetch_set_cards(session: requests.Session, lang_prefix: str, slug: str) -> list[dict]:
    """Fetch first page of cards from a PC set to identify it."""
    url = f"{PC_BASE}/console/pokemon-{lang_prefix}-{slug}"
    try:
        r = session.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
    except Exception:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    cards = []

    # PC lists cards in table rows or product divs
    # Try table rows first
    for row in soup.select("table tr"):
        link = row.select_one("a[href*='/game/']")
        if not link:
            continue
        href = link["href"]
        card_name = link.get_text(strip=True)
        # Extract card slug from URL: /game/pokemon-japanese-{set}/{card-slug}
        parts = href.rstrip("/").split("/")
        if len(parts) >= 2:
            card_slug = parts[-1]
            # Try to extract number from slug: "pikachu-25" -> name=pikachu, num=25
            match = re.match(r"^(.+?)-(\d+)$", card_slug)
            if match:
                cards.append({
                    "name": card_name,
                    "slug_name": match.group(1),
                    "number": match.group(2),
                })
            else:
                cards.append({
                    "name": card_name,
                    "slug_name": card_slug,
                    "number": None,
                })

    # Also try div-based layout
    if not cards:
        for div in soup.select(".product"):
            link = div.select_one("a[href*='/game/']")
            if not link:
                continue
            href = link["href"]
            card_name = link.get_text(strip=True)
            parts = href.rstrip("/").split("/")
            if len(parts) >= 2:
                card_slug = parts[-1]
                match = re.match(r"^(.+?)-(\d+)$", card_slug)
                if match:
                    cards.append({
                        "name": card_name,
                        "slug_name": match.group(1),
                        "number": match.group(2),
                    })

    return cards[:20]  # first 20 is enough for matching


def match_set_to_db(conn: sqlite3.Connection, lang: str, pc_cards: list[dict]) -> str | None:
    """Try to match PC cards to our DB to find the set_id."""
    if not pc_cards:
        return None

    # Strategy: for each PC card with a number, search our DB by eng_name + number
    candidates: dict[str, int] = {}

    for card in pc_cards:
        if not card.get("number"):
            continue
        num = card["number"]
        name = card["name"]

        # Clean up PC name: remove " #123", "Holo", "Reverse" suffixes
        clean_name = re.sub(r"\s*#\d+.*$", "", name).strip()
        clean_name = re.sub(r"\s*(Holo|Reverse|Non).*$", "", clean_name, flags=re.I).strip()

        # Search by eng_name and local_id/collector_number
        rows = conn.execute("""
            SELECT set_id FROM cards
            WHERE language = ?
              AND (eng_name LIKE ? OR name LIKE ?)
              AND (local_id = ? OR collector_number = ?)
        """, (lang, f"%{clean_name}%", f"%{clean_name}%", num, num)).fetchall()

        for row in rows:
            sid = row[0]
            candidates[sid] = candidates.get(sid, 0) + 1

    if not candidates:
        return None

    # Return the set_id with most matches
    best = max(candidates, key=candidates.get)
    count = candidates[best]
    if count >= 2:  # need at least 2 matching cards to be confident
        return best

    return None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true", help="Auto-update build_pricecharting_map.py")
    args = parser.parse_args()

    session = requests.Session()
    conn = sqlite3.connect(str(DB_PATH))

    # Import existing mappings
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_pricecharting_map import JP_SET_SLUGS, TW_SET_SLUGS

    print("=== Scraping PriceCharting set catalog ===\n")
    all_sets = fetch_category_sets(session)

    print(f"Found {len(all_sets['ja'])} JP sets, {len(all_sets['zh-tw'])} TW sets on PriceCharting\n")

    # Find which PC sets we DON'T have mapped
    existing_jp_slugs = set(JP_SET_SLUGS.values())
    existing_tw_slugs = set(TW_SET_SLUGS.values())

    new_jp: list[tuple[str, str, str]] = []  # (slug, pc_name, our_set_id)
    new_tw: list[tuple[str, str, str]] = []

    # Process JP unmapped sets
    unmapped_jp = [(s, n) for s, n in all_sets["ja"] if s not in existing_jp_slugs]
    print(f"JP: {len(unmapped_jp)} sets not in our mapping, attempting to match...\n")

    for i, (slug, pc_name) in enumerate(unmapped_jp):
        print(f"  [{i+1}/{len(unmapped_jp)}] {slug} ({pc_name})...", end=" ", flush=True)
        cards = fetch_set_cards(session, "japanese", slug)
        if not cards:
            print("no cards found")
            time.sleep(0.5)
            continue

        set_id = match_set_to_db(conn, "ja", cards)
        if set_id:
            if set_id not in JP_SET_SLUGS:
                new_jp.append((slug, pc_name, set_id))
                print(f"MATCHED -> {set_id} ({len(cards)} cards sampled)")
            else:
                print(f"already mapped (set_id={set_id})")
        else:
            print(f"no match ({len(cards)} cards sampled)")
        time.sleep(0.5)

    # Process TW unmapped sets
    unmapped_tw = [(s, n) for s, n in all_sets["zh-tw"] if s not in existing_tw_slugs]
    print(f"\nTW: {len(unmapped_tw)} sets not in our mapping, attempting to match...\n")

    for i, (slug, pc_name) in enumerate(unmapped_tw):
        print(f"  [{i+1}/{len(unmapped_tw)}] {slug} ({pc_name})...", end=" ", flush=True)
        cards = fetch_set_cards(session, "chinese", slug)
        if not cards:
            print("no cards found")
            time.sleep(0.5)
            continue

        set_id = match_set_to_db(conn, "zh-tw", cards)
        if set_id:
            if set_id not in TW_SET_SLUGS:
                new_tw.append((slug, pc_name, set_id))
                print(f"MATCHED -> {set_id} ({len(cards)} cards sampled)")
            else:
                print(f"already mapped (set_id={set_id})")
        else:
            print(f"no match ({len(cards)} cards sampled)")
        time.sleep(0.5)

    # Summary
    print(f"\n{'='*60}")
    print(f"NEW JP mappings found: {len(new_jp)}")
    for slug, pc_name, set_id in new_jp:
        print(f'    "{set_id}": "{slug}",  # {pc_name}')

    print(f"\nNEW TW mappings found: {len(new_tw)}")
    for slug, pc_name, set_id in new_tw:
        print(f'    "{set_id}": "{slug}",  # {pc_name}')

    # Also show PC sets that exist but we couldn't match
    all_matched_jp = existing_jp_slugs | {s for s, _, _ in new_jp}
    unmatched_jp = [(s, n) for s, n in all_sets["ja"] if s not in all_matched_jp]
    if unmatched_jp:
        print(f"\nJP PC sets we couldn't auto-match ({len(unmatched_jp)}):")
        for slug, name in unmatched_jp:
            print(f"  {slug} | {name}")

    all_matched_tw = existing_tw_slugs | {s for s, _, _ in new_tw}
    unmatched_tw = [(s, n) for s, n in all_sets["zh-tw"] if s not in all_matched_tw]
    if unmatched_tw:
        print(f"\nTW PC sets we couldn't auto-match ({len(unmatched_tw)}):")
        for slug, name in unmatched_tw:
            print(f"  {slug} | {name}")

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
