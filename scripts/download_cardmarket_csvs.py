from __future__ import annotations

"""
Parse CardMarket product catalog + price guide (JSON format).
Merge into a single cards_with_prices.json with expansion names and grouping.

Input files (download manually from https://www.cardmarket.com/en/Pokemon/Data/Download):
  data/cardmarket/products_singles.json   — product catalog
  data/cardmarket/price_guide.json        — price guide

Usage:
    python scripts/download_cardmarket_csvs.py            # ALL cards (default)
    python scripts/download_cardmarket_csvs.py --year 2025 # from 2025 onwards only
"""

import argparse
import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

DATA_DIR = Path("./data/cardmarket")

PRODUCTS_FILE = DATA_DIR / "products_singles.json"
PRICE_GUIDE_FILE = DATA_DIR / "price_guide.json"
OUTPUT_FILE = DATA_DIR / "cards_with_prices.json"
EXPANSION_MAP_FILE = DATA_DIR / "_expansion_map.json"


# ------------------------------------------------------------------
# Load CardMarket data
# ------------------------------------------------------------------

def load_products(path: Path) -> list[dict]:
    """Load product catalog from CardMarket JSON."""
    print(f"Loading products from {path}...")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    products = data.get("products", [])
    print(f"  Total products: {len(products)}")
    print(f"  Created at: {data.get('createdAt', '?')}")
    return products


def load_prices(path: Path) -> dict[int, dict]:
    """Load price guide into {idProduct: prices} dict."""
    print(f"Loading price guide from {path}...")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    guides = data.get("priceGuides", [])
    print(f"  Total price entries: {len(guides)}")

    prices: dict[int, dict] = {}
    for entry in guides:
        pid = entry["idProduct"]
        prices[pid] = {
            "avg_sell": entry.get("avg") or 0,
            "low": entry.get("low") or 0,
            "trend": entry.get("trend") or 0,
            "avg7": entry.get("avg7") or 0,
            "avg30": entry.get("avg30") or 0,
            "foil_trend": entry.get("trend-holo") or 0,
            "foil_low": entry.get("low-holo") or 0,
        }
    return prices


# ------------------------------------------------------------------
# Build expansion name mapping via TCGdex
# ------------------------------------------------------------------

def _normalize(name: str) -> str:
    """Normalize name for fuzzy matching."""
    name = name.lower().strip()
    name = re.sub(r"[''`\-]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name


def build_expansion_map(products: list[dict]) -> dict[int, str]:
    """Build CardMarket expansion_id -> expansion_name mapping.

    Strategy:
    1. Load cached mapping if available.
    2. Fetch TCGdex set list and detailed set info (card names per set).
    3. For each CM expansion ID, find the TCGdex set with the highest card name overlap.
       Multiple CM expansion IDs can map to the same TCGdex set name
       (e.g. English, Japanese, Italian prints of the same set).
    4. Cache the result.
    """
    # Check cache first
    if EXPANSION_MAP_FILE.exists():
        print(f"Loading expansion map from cache: {EXPANSION_MAP_FILE}")
        with open(EXPANSION_MAP_FILE, "r", encoding="utf-8") as f:
            cached = json.load(f)
        return {int(k): v for k, v in cached.items()}

    print("\nBuilding expansion_id -> name mapping via TCGdex...")

    # Group CM cards by expansion ID  (store normalized names as sets)
    cm_by_exp: dict[int, set[str]] = {}
    for p in products:
        eid = p["idExpansion"]
        cm_by_exp.setdefault(eid, set()).add(_normalize(p.get("name", "")))

    # Fetch all TCGdex sets with their card names
    print("  Fetching TCGdex set list...")
    resp = requests.get("https://api.tcgdex.net/v2/en/sets", timeout=15)
    resp.raise_for_status()
    tcg_sets = resp.json()
    print(f"  {len(tcg_sets)} sets found. Fetching card names for each...")

    # Build {set_name: set_of_normalized_card_names}
    tcg_set_cards: dict[str, set[str]] = {}
    tcg_set_names: dict[str, str] = {}  # set_id -> set_name

    for idx, tcg_set in enumerate(tcg_sets):
        set_id = tcg_set["id"]
        set_name = tcg_set.get("name", set_id)
        tcg_set_names[set_id] = set_name

        try:
            r = requests.get(
                f"https://api.tcgdex.net/v2/en/sets/{set_id}", timeout=15
            )
            if r.status_code != 200:
                continue
            detail = r.json()
        except Exception:
            continue

        card_names = set()
        for card in detail.get("cards", []):
            n = _normalize(card.get("name", ""))
            if n:
                card_names.add(n)

        if card_names:
            tcg_set_cards[set_name] = card_names

        if (idx + 1) % 20 == 0:
            print(f"  Fetched {idx + 1}/{len(tcg_sets)} sets...")

        time.sleep(0.05)

    print(f"  Got card lists for {len(tcg_set_cards)} TCGdex sets.")

    # For each CM expansion ID, find the best matching TCGdex set
    # (many-to-one: multiple CM IDs can map to the same TCGdex set)
    exp_map: dict[int, str] = {}
    match_count = 0

    for eid, cm_names in cm_by_exp.items():
        best_set_name = None
        best_score = 0

        for set_name, tcg_names in tcg_set_cards.items():
            overlap = len(cm_names & tcg_names)
            # Score: overlap relative to the CM expansion size
            if overlap >= 3 and overlap > best_score:
                best_score = overlap
                best_set_name = set_name

        if best_set_name is not None:
            exp_map[eid] = best_set_name
            match_count += 1
        else:
            exp_map[eid] = f"Expansion #{eid}"

    print(f"  Matched {match_count} out of {len(cm_by_exp)} CM expansion IDs.")

    # Cache
    with open(EXPANSION_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {str(k): v for k, v in exp_map.items()},
            f, indent=2, ensure_ascii=False,
        )
    print(f"  Saved expansion map to {EXPANSION_MAP_FILE}")

    return exp_map


# ------------------------------------------------------------------
# Filter and merge
# ------------------------------------------------------------------

def filter_by_year(products: list[dict], min_year: int) -> list[dict]:
    """Keep only products added in min_year or later.
    Products with no date are always included (they may be old promos/exclusives).
    """
    filtered = []
    for p in products:
        date_str = p.get("dateAdded", "")
        if not date_str or date_str == "0000-00-00 00:00:00":
            # Keep cards with no date — they are typically old promos/exclusives
            filtered.append(p)
            continue
        try:
            year = int(date_str[:4])
            if year >= min_year:
                filtered.append(p)
        except (ValueError, IndexError):
            filtered.append(p)  # Keep if date is unparseable
    return filtered


def merge_and_save(
    products: list[dict],
    prices: dict[int, dict],
    exp_map: dict[int, str],
    output: Path,
) -> None:
    """Merge products with prices and expansion names, group by expansion, save."""
    # Build cards list
    cards = []
    for p in products:
        pid = p["idProduct"]
        eid = p.get("idExpansion", 0)
        card_prices = prices.get(pid, {})

        cards.append({
            "id_product": pid,
            "name": p.get("name", ""),
            "category_id": p.get("idCategory", 0),
            "category": p.get("categoryName", ""),
            "expansion_id": eid,
            "expansion_name": exp_map.get(eid, f"Expansion #{eid}"),
            "metacard_id": p.get("idMetacard", 0),
            "date_added": p.get("dateAdded", ""),
            "price_trend": card_prices.get("trend", 0),
            "price_low": card_prices.get("low", 0),
            "price_avg": card_prices.get("avg_sell", 0),
            "price_avg7": card_prices.get("avg7", 0),
            "price_avg30": card_prices.get("avg30", 0),
            "price_foil_trend": card_prices.get("foil_trend", 0),
            "price_foil_low": card_prices.get("foil_low", 0),
        })

    with_prices = sum(1 for c in cards if c["price_trend"])

    # Group by expansion for summary
    exp_groups: dict[str, int] = Counter(c["expansion_name"] for c in cards)

    result = {
        "updated_at": datetime.now().isoformat(),
        "total_cards": len(cards),
        "total_expansions": len(exp_groups),
        "expansions_summary": dict(exp_groups.most_common()),
        "cards": cards,
    }
    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n  Total cards: {len(cards)}")
    print(f"  Cards with prices: {with_prices}")
    print(f"  Total expansions: {len(exp_groups)}")
    print(f"  Saved to {output}")


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Parse CardMarket data")
    parser.add_argument(
        "--year", type=int, default=None,
        help="Minimum year for dateAdded filter (default: include ALL cards)"
    )
    args = parser.parse_args()

    # Check input files
    for f in [PRODUCTS_FILE, PRICE_GUIDE_FILE]:
        if not f.exists():
            print(f"ERROR: {f} not found!")
            print("Download from https://www.cardmarket.com/en/Pokemon/Data/Download")
            print(f"Save as: {f}")
            raise SystemExit(1)

    # Load
    products = load_products(PRODUCTS_FILE)
    prices = load_prices(PRICE_GUIDE_FILE)

    # Build expansion map
    exp_map = build_expansion_map(products)

    # Filter
    if args.year is not None:
        products = filter_by_year(products, args.year)
        print(f"\nFiltered to {args.year}+: {len(products)} products")
    else:
        print(f"\nKeeping ALL {len(products)} products")

    # Stats by expansion
    exp_counter = Counter(exp_map.get(p["idExpansion"], "?") for p in products)
    print(f"Unique expansions: {len(exp_counter)}")
    print(f"Top 15 expansions by card count:")
    for name, cnt in exp_counter.most_common(15):
        print(f"  {name}: {cnt} cards")

    # Merge & save
    merge_and_save(products, prices, exp_map, OUTPUT_FILE)

    print(f"\nDone! {len(products)} cards ready.")
    print(f"Next step: python scripts/download_images_pokemontcg.py")


if __name__ == "__main__":
    main()
