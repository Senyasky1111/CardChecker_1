"""
Enrich card database with PokeTrace Pro API data.

Adds: tcgplayer_id, cardmarket_id (for JP/TW), eBay prices,
TCGPlayer USD prices, CardMarket EUR prices, PSA/BGS/CGC graded prices.

Usage:
    python scripts/enrich_poketrace.py [--phase en|jp|tw|all] [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import POKETRACE_API_KEY, POKETRACE_BASE_URL, POKETRACE_BURST_DELAY
from src.db import ensure_schema

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
NOW = datetime.now(timezone.utc).isoformat()

session = requests.Session()
session.headers["X-API-Key"] = POKETRACE_API_KEY
session.headers["Accept"] = "application/json"

# ── Helpers ──────────────────────────────────────────────────────────

def api_get(endpoint: str, params: dict | None = None, retries: int = 3) -> dict | None:
    """GET with rate limiting and retries."""
    url = f"{POKETRACE_BASE_URL}{endpoint}"
    for attempt in range(retries):
        try:
            time.sleep(POKETRACE_BURST_DELAY)
            r = session.get(url, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 10))
                print(f"  [429] Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            else:
                print(f"  [{r.status_code}] {endpoint} {params}: {r.text[:200]}")
                return None
        except Exception as e:
            print(f"  [ERR] {endpoint}: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


def save_external_id(conn, tcgdex_id: str, card_data: dict, method: str):
    """Save PokeTrace ID + marketplace refs to card_external_ids."""
    refs = card_data.get("refs", {})
    conn.execute("""
        INSERT OR REPLACE INTO card_external_ids
        (tcgdex_id, poketrace_id, tcgplayer_id, poketrace_set_slug, matched_at, match_method)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        tcgdex_id,
        card_data.get("id", ""),
        refs.get("tcgplayerId"),
        card_data.get("set", {}).get("slug", ""),
        NOW,
        method,
    ))

    # Update cards table shortcuts
    tcgplayer_id = refs.get("tcgplayerId")
    cardmarket_id = refs.get("cardmarketId")
    if tcgplayer_id:
        conn.execute("UPDATE cards SET tcgplayer_id = ? WHERE tcgdex_id = ?",
                      (tcgplayer_id, tcgdex_id))
    # Fill missing cm_id_product for JP/TW
    if cardmarket_id:
        conn.execute("""UPDATE cards SET cm_id_product = ?
                        WHERE tcgdex_id = ? AND (cm_id_product IS NULL OR cm_id_product = 0)""",
                     (cardmarket_id, tcgdex_id))


def save_prices(conn, tcgdex_id: str, card_data: dict):
    """Save all price tiers from PokeTrace to prices_external."""
    prices = card_data.get("prices", {})
    currency_map = {"EU": "EUR", "US": "USD"}
    currency = currency_map.get(card_data.get("market", ""), "EUR")

    rows_saved = 0
    for marketplace, tiers in prices.items():
        if not isinstance(tiers, dict):
            continue
        for condition, tier_data in tiers.items():
            if not isinstance(tier_data, dict):
                continue

            # Handle country-level data in cardmarket_unsold
            countries_data = tier_data.pop("country", None) if isinstance(tier_data, dict) else None

            # Save main tier
            _insert_price_row(conn, tcgdex_id, marketplace, condition, "ALL", currency, tier_data)
            rows_saved += 1

            # Save country-level prices if available
            if countries_data and isinstance(countries_data, dict):
                for country_code, country_tier in countries_data.items():
                    if isinstance(country_tier, dict):
                        _insert_price_row(conn, tcgdex_id, marketplace, condition, country_code, currency, country_tier)
                        rows_saved += 1

    # Update summary columns on cards
    top_eur = _get_best_price(prices, "cardmarket")
    top_usd = _get_best_price(prices, "tcgplayer") or _get_best_price(prices, "ebay")
    has_graded = 1 if any(
        cond.startswith(("PSA_", "BGS_", "CGC_", "SGC_", "ACE_", "TAG_"))
        for mp_tiers in prices.values() if isinstance(mp_tiers, dict)
        for cond in mp_tiers.keys()
    ) else 0

    conn.execute("""
        UPDATE cards SET top_price_eur = ?, top_price_usd = ?, has_graded = ?, enriched_at = ?
        WHERE tcgdex_id = ?
    """, (top_eur, top_usd, has_graded, NOW, tcgdex_id))

    return rows_saved


def _insert_price_row(conn, tcgdex_id, marketplace, condition, country, currency, tier):
    """Insert/replace a single price row."""
    conn.execute("""
        INSERT OR REPLACE INTO prices_external
        (tcgdex_id, source, marketplace, condition, country, currency,
         price_avg, price_low, price_high, price_trend,
         avg_1d, avg_7d, avg_30d, sale_count, confidence,
         snapshot_date, updated_at)
        VALUES (?, 'poketrace', ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?)
    """, (
        tcgdex_id, marketplace, condition, country, currency,
        tier.get("avg"), tier.get("low"), tier.get("high"),
        tier.get("trend", ""),
        tier.get("avg1d"), tier.get("avg7d"), tier.get("avg30d"),
        tier.get("saleCount"), tier.get("confidence", ""),
        TODAY, NOW,
    ))


def _get_best_price(prices: dict, marketplace: str) -> float | None:
    """Extract best available price for a marketplace."""
    mp = prices.get(marketplace, {})
    if not isinstance(mp, dict):
        return None
    # Try AGGREGATED first, then NEAR_MINT
    for cond in ["AGGREGATED", "NEAR_MINT"]:
        tier = mp.get(cond, {})
        if isinstance(tier, dict) and tier.get("avg"):
            return tier["avg"]
    return None


# ── Phase A: EN cards by bulk CardMarket ID lookup ───────────────────

def enrich_en_bulk(conn, limit: int = 0, dry_run: bool = False):
    """Enrich EN cards using bulk cardmarket_ids lookup."""
    print("\n=== Phase A: EN cards (bulk CM ID lookup) ===")

    rows = conn.execute("""
        SELECT tcgdex_id, cm_id_product FROM cards
        WHERE language = 'en' AND cm_id_product IS NOT NULL AND cm_id_product > 0
        AND (enriched_at IS NULL OR enriched_at = '')
        ORDER BY cm_id_product
    """).fetchall()

    total = min(len(rows), limit) if limit else len(rows)
    print(f"  Cards to enrich: {total}")

    if dry_run:
        print("  [DRY RUN] Would make ~{} API requests".format((total + 19) // 20))
        return

    # Build cm_id → tcgdex_id map
    cm_to_tcg = {}
    for r in rows[:total]:
        cm_to_tcg[str(r["cm_id_product"])] = r["tcgdex_id"]

    cm_ids = list(cm_to_tcg.keys())
    matched = 0
    total_prices = 0
    batch_size = 20

    for i in range(0, len(cm_ids), batch_size):
        batch = cm_ids[i:i + batch_size]
        batch_str = ",".join(batch)

        data = api_get("/cards", {"cardmarket_ids": batch_str, "market": "EU"})
        if not data or "data" not in data:
            continue

        for card in data["data"]:
            cm_id = str(card.get("refs", {}).get("cardmarketId", ""))
            tcgdex_id = cm_to_tcg.get(cm_id)
            if not tcgdex_id:
                continue

            save_external_id(conn, tcgdex_id, card, "cm_bulk_eu")
            rows_saved = save_prices(conn, tcgdex_id, card)
            total_prices += rows_saved
            matched += 1

        # Also try US market for same batch to get TCGPlayer + eBay
        data_us = api_get("/cards", {"cardmarket_ids": batch_str, "market": "US"})
        if data_us and "data" in data_us:
            for card in data_us["data"]:
                # US cards have tcgplayerId
                refs = card.get("refs", {})
                tcg_id = refs.get("tcgplayerId")
                cm_id = str(refs.get("cardmarketId", ""))
                tcgdex_id = cm_to_tcg.get(cm_id)
                if tcgdex_id and tcg_id:
                    conn.execute("UPDATE cards SET tcgplayer_id = ? WHERE tcgdex_id = ?",
                                 (tcg_id, tcgdex_id))
                    conn.execute("""
                        UPDATE card_external_ids SET tcgplayer_id = ?
                        WHERE tcgdex_id = ?
                    """, (tcg_id, tcgdex_id))
                if tcgdex_id:
                    save_prices(conn, tcgdex_id, card)

        if (i // batch_size + 1) % 50 == 0:
            conn.commit()
            pct = min(100, (i + batch_size) / len(cm_ids) * 100)
            print(f"  Progress: {i + batch_size}/{len(cm_ids)} ({pct:.1f}%) | matched: {matched} | prices: {total_prices}")

    conn.commit()
    print(f"  Done! Matched: {matched}/{total} | Price rows: {total_prices}")


# ── Phase B/C: JP/TW cards ───────────────────────────────────────────

def enrich_lang_cards(conn, lang: str, game: str, limit: int = 0, dry_run: bool = False):
    """Enrich JP or TW cards — bulk for those with CM IDs, search for rest."""
    lang_label = "JP" if lang == "ja" else "TW"
    print(f"\n=== Phase {lang_label}: {lang} cards ===")

    # Part 1: bulk lookup for cards WITH cm_id_product (skip already enriched)
    rows_with_cm = conn.execute("""
        SELECT tcgdex_id, cm_id_product, name, eng_name, collector_number, set_id
        FROM cards WHERE language = ? AND cm_id_product IS NOT NULL AND cm_id_product > 0
        AND (enriched_at IS NULL OR enriched_at = '')
        ORDER BY cm_id_product
    """, (lang,)).fetchall()

    # Part 2: search for cards WITHOUT cm_id_product (skip already enriched)
    rows_without_cm = conn.execute("""
        SELECT tcgdex_id, name, eng_name, collector_number, set_id,
               (SELECT abbreviation FROM sets WHERE sets.set_id = cards.set_id) as abbreviation
        FROM cards WHERE language = ? AND (cm_id_product IS NULL OR cm_id_product = 0)
        AND eng_name != '' AND eng_name IS NOT NULL
        AND (enriched_at IS NULL OR enriched_at = '')
        ORDER BY set_id, collector_number
    """, (lang,)).fetchall()

    total_bulk = min(len(rows_with_cm), limit) if limit else len(rows_with_cm)
    total_search = min(len(rows_without_cm), limit) if limit else len(rows_without_cm)
    est_requests = (total_bulk + 19) // 20 + total_search

    print(f"  Bulk (with CM ID): {total_bulk} cards -> ~{(total_bulk + 19) // 20} requests")
    print(f"  Search (no CM ID): {total_search} cards -> ~{total_search} requests")
    print(f"  Total estimated: ~{est_requests} requests")

    if dry_run:
        print(f"  [DRY RUN] skipping")
        return

    # ── Part 1: Bulk ──
    matched_bulk = 0
    cm_to_tcg = {}
    for r in rows_with_cm[:total_bulk]:
        cm_to_tcg[str(r["cm_id_product"])] = r["tcgdex_id"]

    cm_ids = list(cm_to_tcg.keys())
    for i in range(0, len(cm_ids), 20):
        batch = cm_ids[i:i + 20]
        data = api_get("/cards", {"cardmarket_ids": ",".join(batch), "market": "EU"})
        if data and "data" in data:
            for card in data["data"]:
                cm_id = str(card.get("refs", {}).get("cardmarketId", ""))
                tcgdex_id = cm_to_tcg.get(cm_id)
                if tcgdex_id:
                    save_external_id(conn, tcgdex_id, card, "cm_bulk_eu")
                    save_prices(conn, tcgdex_id, card)
                    matched_bulk += 1

        if (i // 20 + 1) % 50 == 0:
            conn.commit()
            print(f"  Bulk progress: {i + 20}/{len(cm_ids)} | matched: {matched_bulk}")

    conn.commit()
    print(f"  Bulk done: {matched_bulk}/{total_bulk}")

    # ── Part 2: Search ──
    matched_search = 0
    new_cm_ids = 0

    for idx, r in enumerate(rows_without_cm[:total_search]):
        eng_name = r["eng_name"]
        number = r["collector_number"]
        tcgdex_id = r["tcgdex_id"]

        params = {"game": game, "search": eng_name, "limit": 5}
        if number:
            params["card_number"] = str(number)

        data = api_get("/cards", params)
        if not data or "data" not in data or not data["data"]:
            continue

        # Try to match by card number + name
        best = None
        for card in data["data"]:
            card_num = card.get("cardNumber", "")
            if card_num and number and str(number) in str(card_num):
                best = card
                break
        if not best:
            best = data["data"][0]  # take first result

        save_external_id(conn, tcgdex_id, best, "search_" + game)
        save_prices(conn, tcgdex_id, best)
        matched_search += 1

        # Fill cm_id_product if found
        cm_id = best.get("refs", {}).get("cardmarketId")
        if cm_id:
            conn.execute("UPDATE cards SET cm_id_product = ? WHERE tcgdex_id = ?",
                         (cm_id, tcgdex_id))
            new_cm_ids += 1

        if (idx + 1) % 100 == 0:
            conn.commit()
            print(f"  Search progress: {idx + 1}/{total_search} | matched: {matched_search} | new CM IDs: {new_cm_ids}")

    conn.commit()
    print(f"  Search done: {matched_search}/{total_search} | New CM IDs: {new_cm_ids}")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Enrich cards with PokeTrace data")
    parser.add_argument("--phase", choices=["en", "jp", "tw", "all"], default="all")
    parser.add_argument("--limit", type=int, default=0, help="Limit cards per phase (0=all)")
    parser.add_argument("--dry-run", action="store_true", help="Don't make API calls")
    args = parser.parse_args()

    if not POKETRACE_API_KEY:
        print("ERROR: POKETRACE_API_KEY not set. Check .env file.")
        sys.exit(1)

    print(f"PokeTrace Enrichment | Phase: {args.phase} | Limit: {args.limit or 'ALL'}")
    print(f"API Key: {POKETRACE_API_KEY[:10]}...{POKETRACE_API_KEY[-4:]}")

    conn = ensure_schema()

    # Quick stats
    for lang_name, lang_code in [("EN", "en"), ("JP", "ja"), ("TW", "zh-tw")]:
        total = conn.execute("SELECT COUNT(*) FROM cards WHERE language=?", (lang_code,)).fetchone()[0]
        with_cm = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND cm_id_product IS NOT NULL AND cm_id_product > 0", (lang_code,)).fetchone()[0]
        enriched = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND enriched_at != ''", (lang_code,)).fetchone()[0]
        print(f"  {lang_name}: {total} cards | CM: {with_cm} ({100*with_cm/total:.1f}%) | Enriched: {enriched}")

    t0 = time.time()

    if args.phase in ("en", "all"):
        enrich_en_bulk(conn, limit=args.limit, dry_run=args.dry_run)

    if args.phase in ("jp", "all"):
        enrich_lang_cards(conn, "ja", "pokemon-japanese", limit=args.limit, dry_run=args.dry_run)

    if args.phase in ("tw", "all"):
        enrich_lang_cards(conn, "zh-tw", "pokemon-japanese", limit=args.limit, dry_run=args.dry_run)

    elapsed = time.time() - t0
    print(f"\n=== COMPLETE in {elapsed:.0f}s ===")

    # Final stats
    for lang_name, lang_code in [("EN", "en"), ("JP", "ja"), ("TW", "zh-tw")]:
        total = conn.execute("SELECT COUNT(*) FROM cards WHERE language=?", (lang_code,)).fetchone()[0]
        with_cm = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND cm_id_product IS NOT NULL AND cm_id_product > 0", (lang_code,)).fetchone()[0]
        with_tcg = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND tcgplayer_id IS NOT NULL", (lang_code,)).fetchone()[0]
        enriched = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND enriched_at != ''", (lang_code,)).fetchone()[0]
        print(f"  {lang_name}: {total} | CM: {with_cm} ({100*with_cm/total:.1f}%) | TCG: {with_tcg} | Enriched: {enriched}")

    ext_count = conn.execute("SELECT COUNT(*) FROM card_external_ids").fetchone()[0]
    price_count = conn.execute("SELECT COUNT(*) FROM prices_external").fetchone()[0]
    print(f"  External IDs: {ext_count} | Price rows: {price_count}")

    conn.close()


if __name__ == "__main__":
    main()
