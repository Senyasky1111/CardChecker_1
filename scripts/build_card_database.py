"""
Build the SQLite card database from TCGdex API + CardMarket CSVs.

Phases:
    1. Fetch sets from TCGdex API
    2. Fetch cards (tier 1: set stubs, tier 2: full card details)
    3. Load CardMarket prices from local JSON files
    4. Map local image paths

Usage:
    py -3.11 scripts/build_card_database.py              # Full build (resumable)
    py -3.11 scripts/build_card_database.py --prices-only # Just update prices
    py -3.11 scripts/build_card_database.py --force       # Re-fetch everything
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import requests
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db import get_connection, init_db

TCGDEX_BASE = "https://api.tcgdex.net/v2/en"
IMAGES_DIR = Path("./data/cardmarket/images")
CM_PRODUCTS_PATH = Path("./data/cardmarket/products_singles.json")
CM_PRICES_PATH = Path("./data/cardmarket/price_guide.json")

# Reuse normalize_name from text_index
_STRIP_RE = re.compile(r"[\s\-'.,:;!\?\(\)\[\]]+")
_BRACKET_RE = re.compile(r"\s*\[.*?\]")
_PARENS_RE = re.compile(r"\s*\(.*?\)")


def normalize_name(name: str) -> str:
    name = _BRACKET_RE.sub("", name)
    name = _PARENS_RE.sub("", name)
    name = _STRIP_RE.sub("", name)
    return name.lower().strip()


def parse_collector_number(local_id: str) -> int | None:
    """Parse integer collector number from local_id like '057' or 'TG15'."""
    m = re.match(r"^0*(\d+)$", local_id)
    return int(m.group(1)) if m else None


# Reusable session with connection pooling (prevents socket exhaustion)
_session = requests.Session()
_session.headers.update({"User-Agent": "CardRecognition/1.0"})
# Increase pool size for sustained API usage
adapter = requests.adapters.HTTPAdapter(pool_connections=5, pool_maxsize=10)
_session.mount("https://", adapter)
_session.mount("http://", adapter)


def api_get(path: str, retries: int = 5) -> dict | list | None:
    """GET from TCGdex API with retries, rate-limit handling, and connection pooling."""
    url = f"{TCGDEX_BASE}{path}"
    for attempt in range(retries):
        try:
            resp = _session.get(url, timeout=60)
            if resp.status_code == 404:
                return None
            if resp.status_code == 429:
                wait = 60 * (attempt + 1)
                print(f"    RATE-LIMITED (429), waiting {wait}s... [{url}]")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            delay = 2 ** attempt
            if attempt < retries - 1:
                print(f"    RETRY {attempt+1}/{retries}: HTTP {e.response.status_code} — {url} (wait {delay}s)")
                time.sleep(delay)
            else:
                print(f"    FAILED after {retries} retries: HTTP {e.response.status_code} — {url}")
        except Exception as e:
            delay = 2 ** attempt
            if attempt < retries - 1:
                print(f"    RETRY {attempt+1}/{retries}: {type(e).__name__}: {e} — {url} (wait {delay}s)")
                time.sleep(delay)
            else:
                print(f"    FAILED after {retries} retries: {type(e).__name__}: {e} — {url}")
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------
# Phase 1: Fetch sets
# ------------------------------------------------------------------

def fetch_sets(conn):
    """Fetch all sets from TCGdex and insert into the sets table."""
    print("Phase 1: Fetching sets...")
    sets_list = api_get("/sets")
    if not sets_list:
        print("  ERROR: Could not fetch sets list")
        return

    print(f"  Found {len(sets_list)} sets in list, fetching details...")
    count = 0

    for i, s in enumerate(sets_list):
        set_id = s["id"]

        # Check if already fetched
        existing = conn.execute(
            "SELECT set_id FROM sets WHERE set_id = ?", (set_id,)
        ).fetchone()
        if existing:
            count += 1
            continue

        # Fetch full set detail
        detail = api_get(f"/sets/{set_id}")
        time.sleep(0.5)

        if not detail:
            print(f"  SKIP: {set_id} (404)")
            continue

        card_count = detail.get("cardCount", {})
        serie = detail.get("serie", {})
        abbr_data = detail.get("abbreviation", {})
        abbreviation = ""
        if isinstance(abbr_data, dict):
            abbreviation = abbr_data.get("official", "") or ""
        elif isinstance(abbr_data, str):
            abbreviation = abbr_data

        conn.execute(
            """INSERT OR REPLACE INTO sets
               (set_id, name, series, abbreviation, card_count_official,
                card_count_total, release_date, logo_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                set_id,
                detail.get("name", ""),
                serie.get("name", "") if isinstance(serie, dict) else "",
                abbreviation,
                card_count.get("official", 0),
                card_count.get("total", 0),
                detail.get("releaseDate", ""),
                detail.get("logo", ""),
            ),
        )
        count += 1

        if (i + 1) % 20 == 0:
            conn.commit()
            print(f"  {i + 1}/{len(sets_list)} sets processed")

    conn.commit()
    print(f"  Done: {count} sets in database")


# ------------------------------------------------------------------
# Phase 2: Fetch cards
# ------------------------------------------------------------------

def fetch_cards(conn, force: bool = False, skip_tier2: bool = False):
    """Fetch cards from TCGdex: set stubs first, then full details."""
    print("Phase 2: Fetching cards...")

    sets = conn.execute("SELECT set_id, name FROM sets ORDER BY set_id").fetchall()
    total_inserted = 0
    total_updated = 0
    failed_sets = []
    failed_cards = []
    set_times = []

    for si, s in enumerate(sets):
        set_id = s["set_id"]
        set_name = s["name"]
        set_t0 = time.time()

        try:
            # Tier 1: Get card stubs from set endpoint
            detail = api_get(f"/sets/{set_id}")
            time.sleep(0.3)

            if not detail or "cards" not in detail:
                print(f"  [{si+1}/{len(sets)}] {set_id} \"{set_name}\": SKIP (no cards)")
                continue

            stubs = detail["cards"]
            inserted = 0

            for stub in stubs:
                tcgdex_id = stub.get("id", "")
                if not tcgdex_id:
                    continue

                local_id = stub.get("localId", "")
                name = stub.get("name", "")
                image_url = stub.get("image", "")

                # Insert basic row if not exists
                existing = conn.execute(
                    "SELECT tcgdex_id FROM cards WHERE tcgdex_id = ?", (tcgdex_id,)
                ).fetchone()

                if not existing:
                    conn.execute(
                        """INSERT INTO cards
                           (tcgdex_id, set_id, local_id, collector_number,
                            name, name_normalized, image_url)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            tcgdex_id,
                            set_id,
                            local_id,
                            parse_collector_number(local_id),
                            name,
                            normalize_name(name),
                            image_url,
                        ),
                    )
                    inserted += 1

            conn.commit()
            total_inserted += inserted

            # Tier 2: Fetch full details for unfetched cards
            unfetched_count = 0
            if not skip_tier2:
                if force:
                    unfetched = conn.execute(
                        "SELECT tcgdex_id FROM cards WHERE set_id = ?",
                        (set_id,),
                    ).fetchall()
                else:
                    unfetched = conn.execute(
                        "SELECT tcgdex_id FROM cards WHERE set_id = ? AND fetched_at = ''",
                        (set_id,),
                    ).fetchall()

                unfetched_count = len(unfetched)

                if unfetched:
                    updated = 0
                    for ui, row in enumerate(unfetched):
                        tid = row["tcgdex_id"]
                        try:
                            full = api_get(f"/cards/{tid}")
                            time.sleep(0.5)

                            if not full:
                                continue

                            pricing = full.get("pricing", {}) or {}
                            cm_pricing = pricing.get("cardmarket", {}) or {}
                            cm_id = cm_pricing.get("idProduct")

                            conn.execute(
                                """UPDATE cards SET
                                   rarity = ?, category = ?, hp = ?,
                                   illustrator = ?, cm_id_product = ?,
                                   fetched_at = ?
                                   WHERE tcgdex_id = ?""",
                                (
                                    full.get("rarity", ""),
                                    full.get("category", ""),
                                    full.get("hp"),
                                    full.get("illustrator", ""),
                                    cm_id,
                                    now_iso(),
                                    tid,
                                ),
                            )
                            updated += 1
                        except Exception as e:
                            print(f"    ERROR card {tid}: {type(e).__name__}: {e}")
                            failed_cards.append(tid)
                            continue

                        if (ui + 1) % 50 == 0:
                            conn.commit()
                            print(f"    {set_id}: {ui + 1}/{len(unfetched)} cards updated")

                    conn.commit()
                    total_updated += updated

            # Progress with ETA
            set_elapsed = time.time() - set_t0
            set_times.append(set_elapsed)
            remaining = len(sets) - (si + 1)
            avg_time = sum(set_times) / len(set_times)
            eta_s = remaining * avg_time
            eta_str = f"{eta_s/60:.0f}m" if eta_s > 60 else f"{eta_s:.0f}s"

            tier2_info = f", {unfetched_count} tier2" if not skip_tier2 else ""
            print(f"  [{si+1}/{len(sets)}] {set_id} \"{set_name}\": +{inserted} new{tier2_info} ({set_elapsed:.1f}s, ETA ~{eta_str})")

        except Exception as e:
            print(f"  [{si+1}/{len(sets)}] FATAL {set_id} \"{set_name}\": {type(e).__name__}: {e}")
            failed_sets.append(set_id)
            conn.rollback()
            continue

    print(f"  Done: +{total_inserted} inserted, {total_updated} updated")
    if failed_sets:
        print(f"  FAILED SETS ({len(failed_sets)}): {', '.join(failed_sets)}")
    if failed_cards:
        print(f"  FAILED CARDS ({len(failed_cards)}): {', '.join(failed_cards[:20])}{'...' if len(failed_cards) > 20 else ''}")


# ------------------------------------------------------------------
# Phase 3: Load CardMarket prices
# ------------------------------------------------------------------

def load_prices(conn):
    """Load prices from CardMarket JSON downloads."""
    print("Phase 3: Loading CardMarket prices...")

    # Load products (for cm_name and cm_expansion_id)
    products_by_id = {}
    if CM_PRODUCTS_PATH.exists():
        with open(CM_PRODUCTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for p in data.get("products", []):
            products_by_id[p["idProduct"]] = p
        print(f"  Loaded {len(products_by_id)} products from {CM_PRODUCTS_PATH.name}")

    # Load price guide
    prices_by_id = {}
    if CM_PRICES_PATH.exists():
        with open(CM_PRICES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for p in data.get("priceGuides", []):
            prices_by_id[p["idProduct"]] = p
        print(f"  Loaded {len(prices_by_id)} prices from {CM_PRICES_PATH.name}")

    # Merge and insert
    all_ids = set(products_by_id.keys()) | set(prices_by_id.keys())
    ts = now_iso()
    count = 0

    for pid in all_ids:
        prod = products_by_id.get(pid, {})
        price = prices_by_id.get(pid, {})

        conn.execute(
            """INSERT OR REPLACE INTO prices
               (cm_id_product, cm_name, cm_expansion_id,
                avg, low, trend, avg1, avg7, avg30,
                foil_trend, foil_low, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pid,
                prod.get("name", ""),
                prod.get("idExpansion"),
                price.get("avg", 0) or 0,
                price.get("low", 0) or 0,
                price.get("trend", 0) or 0,
                price.get("avg1"),
                price.get("avg7"),
                price.get("avg30"),
                price.get("trend-holo", 0) or 0,
                price.get("low-holo", 0) or 0,
                ts,
            ),
        )
        count += 1

        if count % 10000 == 0:
            conn.commit()

    conn.commit()
    print(f"  Done: {count} price entries")


# ------------------------------------------------------------------
# Phase 4: Map local image paths
# ------------------------------------------------------------------

def map_images(conn):
    """Scan local images and update image_local in cards table."""
    print("Phase 4: Mapping local images...")

    if not IMAGES_DIR.exists():
        print("  SKIP: images directory not found")
        return

    count = 0
    for set_dir in sorted(IMAGES_DIR.iterdir()):
        if not set_dir.is_dir():
            continue

        for img in set_dir.glob("en_*.jpg"):
            # Parse tcgdex_id from filename: en_sv08-057.jpg → sv08-057
            stem = img.stem  # "en_sv08-057"
            tcgdex_id = stem[3:]  # remove "en_"

            rel_path = f"images/{set_dir.name}/{img.name}"
            conn.execute(
                "UPDATE cards SET image_local = ? WHERE tcgdex_id = ?",
                (rel_path, tcgdex_id),
            )
            count += 1

    conn.commit()
    print(f"  Done: {count} images mapped")


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def print_stats(conn):
    """Print database statistics."""
    sets_count = conn.execute("SELECT count(*) FROM sets").fetchone()[0]
    cards_count = conn.execute("SELECT count(*) FROM cards").fetchone()[0]
    cards_fetched = conn.execute("SELECT count(*) FROM cards WHERE fetched_at != ''").fetchone()[0]
    cards_with_cm = conn.execute("SELECT count(*) FROM cards WHERE cm_id_product IS NOT NULL").fetchone()[0]
    cards_with_img = conn.execute("SELECT count(*) FROM cards WHERE image_local != ''").fetchone()[0]
    prices_count = conn.execute("SELECT count(*) FROM prices").fetchone()[0]

    print(f"\n=== Database Stats ===")
    print(f"Sets:                  {sets_count}")
    print(f"Cards (total):         {cards_count}")
    print(f"Cards (fully fetched): {cards_fetched}")
    print(f"Cards (with CM link):  {cards_with_cm}")
    print(f"Cards (with image):    {cards_with_img}")
    print(f"Prices:                {prices_count}")


def main():
    parser = argparse.ArgumentParser(description="Build card database from TCGdex + CardMarket")
    parser.add_argument("--force", action="store_true", help="Re-fetch all cards")
    parser.add_argument("--prices-only", action="store_true", help="Only update prices")
    parser.add_argument("--images-only", action="store_true", help="Only map local images")
    parser.add_argument("--skip-tier2", action="store_true",
                        help="Skip per-card API calls (Tier 2). Faster, but no rarity/cm_id.")
    parser.add_argument("--db", default=None, help="Database path (default: data/cards.db)")
    args = parser.parse_args()

    conn = get_connection(args.db)
    init_db(conn)

    if args.prices_only:
        load_prices(conn)
    elif args.images_only:
        map_images(conn)
    else:
        fetch_sets(conn)
        fetch_cards(conn, force=args.force, skip_tier2=args.skip_tier2)
        load_prices(conn)
        map_images(conn)

    print_stats(conn)
    conn.close()


if __name__ == "__main__":
    main()
