"""
Enrich cards with PokeTrace US market data (TCGPlayer + eBay prices).

Uses name-based search to find US market listings.
Adds: tcgplayer_id, TCGPlayer prices, eBay sold prices (raw + PSA/BGS/CGC graded).

Usage:
    python scripts/enrich_us_market.py [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import POKETRACE_API_KEY, POKETRACE_BASE_URL, POKETRACE_BURST_DELAY
from src.db import ensure_schema

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
NOW = datetime.now(timezone.utc).isoformat()

session = requests.Session()
session.headers["X-API-Key"] = POKETRACE_API_KEY
session.headers["Accept"] = "application/json"

api_calls = 0


def api_get(endpoint: str, params: dict | None = None, retries: int = 3) -> dict | None:
    """GET with rate limiting and retries."""
    global api_calls
    url = f"{POKETRACE_BASE_URL}{endpoint}"
    for attempt in range(retries):
        try:
            time.sleep(POKETRACE_BURST_DELAY)
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
                return None
        except Exception as e:
            print(f"  [ERR] {endpoint}: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


def save_us_prices(conn, tcgdex_id: str, card_data: dict) -> int:
    """Save US market prices (TCGPlayer + eBay) from PokeTrace."""
    prices = card_data.get("prices", {})
    rows = 0

    for marketplace, tiers in prices.items():
        if not isinstance(tiers, dict):
            continue
        for condition, tier_data in tiers.items():
            if not isinstance(tier_data, dict):
                continue

            conn.execute("""
                INSERT OR REPLACE INTO prices_external
                (tcgdex_id, source, marketplace, condition, country, currency,
                 price_avg, price_low, price_high, price_trend,
                 avg_1d, avg_7d, avg_30d, sale_count, confidence,
                 snapshot_date, updated_at)
                VALUES (?, 'poketrace', ?, ?, 'ALL', 'USD',
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?)
            """, (
                tcgdex_id, marketplace, condition,
                tier_data.get("avg"), tier_data.get("low"), tier_data.get("high"),
                tier_data.get("trend", ""),
                tier_data.get("avg1d"), tier_data.get("avg7d"), tier_data.get("avg30d"),
                tier_data.get("saleCount"), tier_data.get("confidence", ""),
                TODAY, NOW,
            ))
            rows += 1

    return rows


def match_us_card(card_data: dict, target_number: int | None, target_set_slug: str) -> bool:
    """Check if a US search result matches our target card."""
    card_num_str = card_data.get("cardNumber", "")
    if not card_num_str or target_number is None:
        return False

    # Extract number from "045/185" or "45" format
    try:
        num_part = card_num_str.split("/")[0].lstrip("0")
        if not num_part:
            num_part = "0"
        card_num = int(num_part)
    except (ValueError, IndexError):
        return False

    if card_num != target_number:
        return False

    # Optionally check set slug
    if target_set_slug:
        us_set = card_data.get("set", {}).get("slug", "").lower()
        target_norm = target_set_slug.lower().replace("-", "").replace(".", "")
        us_norm = us_set.replace("-", "").replace(".", "")
        if target_norm and us_norm and target_norm not in us_norm and us_norm not in target_norm:
            return False

    return True


def main():
    parser = argparse.ArgumentParser(description="Enrich cards with US market data (TCGPlayer + eBay)")
    parser.add_argument("--limit", type=int, default=5000, help="Limit cards to process (default: 5000)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not POKETRACE_API_KEY:
        print("ERROR: POKETRACE_API_KEY not set.")
        sys.exit(1)

    print(f"PokeTrace US Market Enrichment (search) | Limit: {args.limit}")
    conn = ensure_schema()

    # Get top cards by value that don't have TCGPlayer ID yet
    rows = conn.execute("""
        SELECT c.tcgdex_id, c.eng_name, c.name, c.collector_number,
               c.set_id, c.language,
               cei.poketrace_set_slug
        FROM cards c
        LEFT JOIN card_external_ids cei ON c.tcgdex_id = cei.tcgdex_id
        WHERE c.language = 'en'
        AND (c.tcgplayer_id IS NULL OR c.tcgplayer_id = 0)
        AND c.eng_name IS NOT NULL AND c.eng_name != ''
        ORDER BY COALESCE(c.top_price_eur, 0) DESC
        LIMIT ?
    """, (args.limit,)).fetchall()

    print(f"  Cards to search: {len(rows)}")

    if args.dry_run:
        for r in rows[:10]:
            print(f"  [DRY] {r['eng_name'][:30]:30s} #{r['collector_number']} ({r['set_id']})")
        print("  [DRY RUN] skipping")
        return

    matched = 0
    total_prices = 0

    for idx, r in enumerate(rows):
        eng_name = r["eng_name"]
        number = r["collector_number"]
        tcgdex_id = r["tcgdex_id"]
        set_slug = r["poketrace_set_slug"] or ""

        data = api_get("/cards", {"search": eng_name, "market": "US", "limit": 5})
        if not data or "data" not in data or not data["data"]:
            continue

        # Find best match by card number
        best = None
        for card in data["data"]:
            if match_us_card(card, number, set_slug):
                best = card
                break

        if not best:
            # Take first result if only 1 returned
            if len(data["data"]) == 1:
                best = data["data"][0]
            else:
                continue

        # Save TCGPlayer ID
        refs = best.get("refs", {})
        tcg_id = refs.get("tcgplayerId")
        if tcg_id:
            conn.execute("UPDATE cards SET tcgplayer_id = ? WHERE tcgdex_id = ?", (tcg_id, tcgdex_id))
            conn.execute("""
                UPDATE card_external_ids SET tcgplayer_id = ? WHERE tcgdex_id = ?
            """, (tcg_id, tcgdex_id))

        p = save_us_prices(conn, tcgdex_id, best)
        total_prices += p
        matched += 1

        # Update top_price_usd
        prices = best.get("prices", {})
        for mp in ["tcgplayer", "ebay"]:
            mp_data = prices.get(mp, {})
            if isinstance(mp_data, dict):
                for cond in ["AGGREGATED", "NEAR_MINT"]:
                    tier = mp_data.get(cond, {})
                    if isinstance(tier, dict) and tier.get("avg"):
                        conn.execute("""UPDATE cards SET top_price_usd = ?
                                        WHERE tcgdex_id = ? AND (top_price_usd IS NULL OR top_price_usd = 0)""",
                                     (tier["avg"], tcgdex_id))
                        break

        # Mark graded
        has_graded = any(
            cond.startswith(("PSA_", "BGS_", "CGC_", "SGC_", "ACE_", "TAG_"))
            for mp_tiers in prices.values() if isinstance(mp_tiers, dict)
            for cond in mp_tiers.keys()
        )
        if has_graded:
            conn.execute("UPDATE cards SET has_graded = 1 WHERE tcgdex_id = ?", (tcgdex_id,))

        if (idx + 1) % 100 == 0:
            conn.commit()
            print(f"  Progress: {idx + 1}/{len(rows)} | matched: {matched} | prices: {total_prices} | api: {api_calls}")

    conn.commit()

    print(f"\n=== US MARKET COMPLETE ===")
    print(f"  API calls: {api_calls}")
    print(f"  Cards matched: {matched}/{len(rows)}")
    print(f"  Price rows added: {total_prices}")

    tp = conn.execute("SELECT COUNT(*) FROM cards WHERE tcgplayer_id IS NOT NULL AND tcgplayer_id > 0").fetchone()[0]
    usd = conn.execute("SELECT COUNT(*) FROM cards WHERE top_price_usd IS NOT NULL AND top_price_usd > 0").fetchone()[0]
    print(f"  TCGPlayer IDs: {tp}")
    print(f"  Has USD price: {usd}")

    conn.close()


if __name__ == "__main__":
    main()
