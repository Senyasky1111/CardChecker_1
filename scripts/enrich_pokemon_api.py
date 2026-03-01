"""
Enrich card database with Pokemon-API.com (tcggo) data via RapidAPI.

Adds: country-specific CardMarket prices (DE/FR/ES/IT/EU_only),
7d/30d averages, PSA/CGC graded prices, TCGPlayer USD prices,
cardmarket_id for cards missing it.

Usage:
    python scripts/enrich_pokemon_api.py [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import POKEMON_API_RAPIDAPI_KEY, POKEMON_API_DELAY
from src.db import ensure_schema

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
NOW = datetime.now(timezone.utc).isoformat()

BASE_URL = "https://pokemon-tcg-api.p.rapidapi.com"

session = requests.Session()
session.headers["X-RapidAPI-Key"] = POKEMON_API_RAPIDAPI_KEY
session.headers["X-RapidAPI-Host"] = "pokemon-tcg-api.p.rapidapi.com"
session.headers["Accept"] = "application/json"

api_calls = 0


def api_get(endpoint: str, params: dict | None = None, retries: int = 3) -> dict | list | None:
    """GET with rate limiting and retries."""
    global api_calls
    url = f"{BASE_URL}{endpoint}"
    for attempt in range(retries):
        try:
            time.sleep(POKEMON_API_DELAY)
            r = session.get(url, params=params, timeout=15)
            api_calls += 1
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 10))
                print(f"  [429] Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            else:
                print(f"  [{r.status_code}] {endpoint}: {r.text[:200]}")
                return None
        except Exception as e:
            print(f"  [ERR] {endpoint}: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


def fetch_all_episodes() -> list:
    """Fetch all episodes with pagination."""
    all_eps = []
    page = 1
    while True:
        data = api_get("/episodes", {"page": page})
        if not data:
            break
        eps = data if isinstance(data, list) else data.get("data", [])
        if not eps:
            break
        all_eps.extend(eps)
        print(f"  Page {page}: {len(eps)} episodes (total: {len(all_eps)})")
        if len(eps) < 20:  # last page
            break
        page += 1
    return all_eps


def normalize_code(code: str) -> str:
    """Normalize set code for matching."""
    return (code or "").strip().lower().replace(" ", "").replace("-", "").replace(".", "")


def build_set_mapping(conn) -> dict:
    """Build mapping from normalized abbreviation/name → our set_id."""
    rows = conn.execute("""
        SELECT set_id, abbreviation, name FROM sets WHERE language = 'en'
    """).fetchall()

    mapping = {}
    for s in rows:
        norm = normalize_code(s["abbreviation"])
        if norm:
            mapping[norm] = s["set_id"]
        # Name-based fallback
        name_norm = normalize_code(s["name"])
        if name_norm and name_norm not in mapping:
            mapping[name_norm] = s["set_id"]
    return mapping


def match_card_to_db(conn, card: dict, set_id: str) -> str | None:
    """Match Pokemon-API card to our DB by set + number."""
    card_number = card.get("card_number")
    if card_number is None:
        return None

    # Try by collector_number (integer)
    if isinstance(card_number, int) or (isinstance(card_number, str) and card_number.isdigit()):
        num = int(card_number)
        row = conn.execute("""
            SELECT tcgdex_id FROM cards WHERE set_id = ? AND collector_number = ? AND language = 'en'
        """, (set_id, num)).fetchone()
        if row:
            return row["tcgdex_id"]

    # Try by local_id (string)
    row = conn.execute("""
        SELECT tcgdex_id FROM cards WHERE set_id = ? AND local_id = ? AND language = 'en'
    """, (set_id, str(card_number))).fetchone()
    return row["tcgdex_id"] if row else None


def save_card_prices(conn, tcgdex_id: str, card: dict) -> int:
    """Save prices from Pokemon-API to prices_external."""
    prices = card.get("prices", {})
    if not prices:
        return 0

    papi_id = card.get("id")
    cm_id = card.get("cardmarket_id")
    tcg_id = card.get("tcgplayer_id")

    # Save external IDs
    conn.execute("""
        INSERT INTO card_external_ids (tcgdex_id, pokemon_api_id, tcgplayer_id, matched_at, match_method)
        VALUES (?, ?, ?, ?, 'pokemon_api_set')
        ON CONFLICT(tcgdex_id) DO UPDATE SET
            pokemon_api_id = excluded.pokemon_api_id,
            tcgplayer_id = COALESCE(card_external_ids.tcgplayer_id, excluded.tcgplayer_id)
    """, (tcgdex_id, papi_id, tcg_id, NOW))

    # Fill missing cm_id_product
    if cm_id:
        conn.execute("""
            UPDATE cards SET cm_id_product = ?
            WHERE tcgdex_id = ? AND (cm_id_product IS NULL OR cm_id_product = 0)
        """, (cm_id, tcgdex_id))

    rows = 0
    cm = prices.get("cardmarket", {})
    if cm and isinstance(cm, dict):
        # Overall lowest NM + averages
        if cm.get("lowest_near_mint"):
            conn.execute("""
                INSERT OR REPLACE INTO prices_external
                (tcgdex_id, source, marketplace, condition, country, currency,
                 price_low, avg_7d, avg_30d, snapshot_date, updated_at)
                VALUES (?, 'pokemon_api', 'cardmarket', 'NEAR_MINT', 'ALL', 'EUR',
                        ?, ?, ?, ?, ?)
            """, (tcgdex_id, cm["lowest_near_mint"],
                  cm.get("7d_average"), cm.get("30d_average"), TODAY, NOW))
            rows += 1

        # EU-only prices
        if cm.get("lowest_near_mint_EU_only"):
            conn.execute("""
                INSERT OR REPLACE INTO prices_external
                (tcgdex_id, source, marketplace, condition, country, currency,
                 price_low, snapshot_date, updated_at)
                VALUES (?, 'pokemon_api', 'cardmarket', 'NEAR_MINT', 'EU', 'EUR', ?, ?, ?)
            """, (tcgdex_id, cm["lowest_near_mint_EU_only"], TODAY, NOW))
            rows += 1

        # Country-specific: DE, FR, ES, IT (both full and EU-only)
        for country in ["DE", "FR", "ES", "IT"]:
            val = cm.get(f"lowest_near_mint_{country}")
            if val:
                conn.execute("""
                    INSERT OR REPLACE INTO prices_external
                    (tcgdex_id, source, marketplace, condition, country, currency,
                     price_low, snapshot_date, updated_at)
                    VALUES (?, 'pokemon_api', 'cardmarket', 'NEAR_MINT', ?, 'EUR', ?, ?, ?)
                """, (tcgdex_id, country, val, TODAY, NOW))
                rows += 1

            val_eu = cm.get(f"lowest_near_mint_{country}_EU_only")
            if val_eu and val_eu != val:
                conn.execute("""
                    INSERT OR REPLACE INTO prices_external
                    (tcgdex_id, source, marketplace, condition, country, currency,
                     price_low, confidence, snapshot_date, updated_at)
                    VALUES (?, 'pokemon_api', 'cardmarket', 'NEAR_MINT_EU', ?, 'EUR', ?, 'eu_only', ?, ?)
                """, (tcgdex_id, country, val_eu, TODAY, NOW))
                rows += 1

        # Graded prices
        graded = cm.get("graded", {})
        if graded and isinstance(graded, dict):
            for grader, grades in graded.items():
                if isinstance(grades, dict):
                    for grade_key, grade_val in grades.items():
                        if grade_val:
                            cond = grade_key.upper()
                            if not cond.startswith(("PSA_", "CGC_", "BGS_")):
                                cond = f"{grader.upper()}_{grade_key.upper()}"
                            conn.execute("""
                                INSERT OR REPLACE INTO prices_external
                                (tcgdex_id, source, marketplace, condition, country, currency,
                                 price_avg, snapshot_date, updated_at)
                                VALUES (?, 'pokemon_api', 'cardmarket', ?, 'ALL', 'EUR', ?, ?, ?)
                            """, (tcgdex_id, cond, grade_val, TODAY, NOW))
                            rows += 1

    # TCGPlayer prices
    tcg = prices.get("tcg_player", {})
    if tcg and isinstance(tcg, dict):
        market = tcg.get("market_price")
        mid = tcg.get("mid_price")
        if market or mid:
            conn.execute("""
                INSERT OR REPLACE INTO prices_external
                (tcgdex_id, source, marketplace, condition, country, currency,
                 price_avg, price_high, snapshot_date, updated_at)
                VALUES (?, 'pokemon_api', 'tcgplayer', 'NEAR_MINT', 'ALL', 'USD', ?, ?, ?, ?)
            """, (tcgdex_id, market, mid, TODAY, NOW))
            rows += 1

    return rows


def main():
    parser = argparse.ArgumentParser(description="Enrich cards with Pokemon-API.com data")
    parser.add_argument("--limit", type=int, default=0, help="Limit episodes to process")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not POKEMON_API_RAPIDAPI_KEY:
        print("ERROR: POKEMON_API_RAPIDAPI_KEY not set.")
        sys.exit(1)

    print(f"Pokemon-API.com Enrichment | Limit: {args.limit or 'ALL'}")
    conn = ensure_schema()

    # Step 1: Fetch all episodes
    print("\nFetching all episodes...")
    episodes = fetch_all_episodes()
    print(f"  Total episodes: {len(episodes)}")

    # Build our set mapping
    set_mapping = build_set_mapping(conn)
    print(f"  Our set codes: {len(set_mapping)} entries")

    # Step 2: Match episodes to our sets
    matched_episodes = []
    for ep in episodes:
        ep_code = normalize_code(ep.get("code", ""))
        ep_name = normalize_code(ep.get("name", ""))
        ep_slug = normalize_code(ep.get("slug", ""))
        our_set = set_mapping.get(ep_code) or set_mapping.get(ep_name) or set_mapping.get(ep_slug)

        # Try partial match
        if not our_set:
            for key, sid in set_mapping.items():
                if ep_code and (ep_code in key or key in ep_code):
                    our_set = sid
                    break

        if our_set:
            matched_episodes.append((ep, our_set))

    print(f"  Matched episodes: {len(matched_episodes)}/{len(episodes)}")

    if args.limit:
        matched_episodes = matched_episodes[:args.limit]

    if args.dry_run:
        for ep, sid in matched_episodes:
            print(f"  [DRY] {ep.get('code', '???'):8s} {ep.get('name', ''):30s} -> {sid}")
        return

    # Step 3: Process each matched episode
    total_matched = 0
    total_prices = 0
    new_cm_ids = 0

    for idx, (ep, our_set_id) in enumerate(matched_episodes):
        ep_id = ep["id"]
        ep_code = ep.get("code", "?")
        ep_name = ep.get("name", "?")

        # Fetch cards for this episode
        cards_data = api_get(f"/episodes/{ep_id}/cards")
        if not cards_data:
            continue

        cards = cards_data if isinstance(cards_data, list) else cards_data.get("data", [])

        matched = 0
        prices = 0
        new_cm = 0

        for card in cards:
            tcgdex_id = match_card_to_db(conn, card, our_set_id)
            if not tcgdex_id:
                continue

            p = save_card_prices(conn, tcgdex_id, card)
            prices += p
            matched += 1

            # Count new CM IDs
            cm_id = card.get("cardmarket_id")
            if cm_id:
                new_cm += 1

        conn.commit()
        total_matched += matched
        total_prices += prices
        new_cm_ids += new_cm

        if matched > 0:
            print(f"  [{idx+1}/{len(matched_episodes)}] {ep_code:8s} {ep_name:35s} -> {our_set_id:15s} | {matched}/{len(cards)} cards | {prices} prices")

    print(f"\n=== COMPLETE ===")
    print(f"  API calls: {api_calls}")
    print(f"  Episodes processed: {len(matched_episodes)}")
    print(f"  Cards matched: {total_matched}")
    print(f"  Price rows added: {total_prices}")
    print(f"  New CardMarket IDs: {new_cm_ids}")

    # Final coverage
    for lang_name, lang_code in [("EN", "en")]:
        total = conn.execute("SELECT COUNT(*) FROM cards WHERE language=?", (lang_code,)).fetchone()[0]
        with_cm = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND cm_id_product IS NOT NULL AND cm_id_product > 0", (lang_code,)).fetchone()[0]
        pe = conn.execute("SELECT COUNT(*) FROM prices_external WHERE source='pokemon_api'").fetchone()[0]
        print(f"  {lang_name}: {total} cards | CM: {with_cm} ({100*with_cm/total:.1f}%) | Pokemon-API prices: {pe}")

    conn.close()


if __name__ == "__main__":
    main()
