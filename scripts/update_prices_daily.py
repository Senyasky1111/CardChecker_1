"""
Daily price update script.

Refreshes prices from PokeTrace and Pokemon-API within daily rate limits.
Prioritizes high-value and stale cards.

Usage:
    python scripts/update_prices_daily.py [--dry-run] [--poketrace-only] [--pokemon-api-only]

Schedule (Windows Task Scheduler or cron):
    # Daily at 3:00 AM UTC
    0 3 * * * cd /path/to/CardRecognition && ./venv/Scripts/python.exe scripts/update_prices_daily.py
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import (
    POKETRACE_API_KEY, POKETRACE_BASE_URL, POKETRACE_BURST_DELAY,
    POKEMON_API_RAPIDAPI_KEY, POKEMON_API_DELAY,
)
from src.db import ensure_schema

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
NOW = datetime.now(timezone.utc).isoformat()

# PokeTrace: 10,000 req/day, allocate 8,000 for daily refresh
POKETRACE_DAILY_BUDGET = 8000
# Pokemon-API: 15,000 req/day via RapidAPI, allocate 3,000
POKEMON_API_DAILY_BUDGET = 3000

# -- PokeTrace session --
pt_session = requests.Session()
pt_session.headers["X-API-Key"] = POKETRACE_API_KEY
pt_session.headers["Accept"] = "application/json"

# -- Pokemon-API session --
pa_session = requests.Session()
pa_session.headers["X-RapidAPI-Key"] = POKEMON_API_RAPIDAPI_KEY
pa_session.headers["X-RapidAPI-Host"] = "pokemon-tcg-api.p.rapidapi.com"
pa_session.headers["Accept"] = "application/json"

pt_calls = 0
pa_calls = 0


def pt_get(endpoint, params=None, retries=3):
    """PokeTrace GET with rate limit."""
    global pt_calls
    for attempt in range(retries):
        try:
            time.sleep(POKETRACE_BURST_DELAY)
            r = pt_session.get(f"{POKETRACE_BASE_URL}{endpoint}", params=params, timeout=15)
            pt_calls += 1
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 10))
                print(f"  [PT 429] waiting {wait}s...")
                time.sleep(wait)
                continue
            else:
                return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


def pa_get(endpoint, params=None, retries=3):
    """Pokemon-API GET with rate limit."""
    global pa_calls
    base = "https://pokemon-tcg-api.p.rapidapi.com"
    for attempt in range(retries):
        try:
            time.sleep(POKEMON_API_DELAY)
            r = pa_session.get(f"{base}{endpoint}", params=params, timeout=15)
            pa_calls += 1
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 10))
                print(f"  [PA 429] waiting {wait}s...")
                time.sleep(wait)
                continue
            else:
                return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


def update_poketrace(conn, dry_run=False):
    """Update prices from PokeTrace, prioritizing high-value and stale cards."""
    print("\n=== PokeTrace Daily Update ===")

    # Priority 1: Top 5000 cards by price (most valuable)
    top_cards = conn.execute("""
        SELECT tcgdex_id, cm_id_product FROM cards
        WHERE cm_id_product IS NOT NULL AND cm_id_product > 0
        ORDER BY COALESCE(top_price_eur, 0) + COALESCE(top_price_usd, 0) DESC
        LIMIT 5000
    """).fetchall()

    # Priority 2: Cards with stale prices (>7 days)
    stale_cards = conn.execute("""
        SELECT c.tcgdex_id, c.cm_id_product FROM cards c
        WHERE c.cm_id_product IS NOT NULL AND c.cm_id_product > 0
        AND (c.enriched_at IS NULL OR c.enriched_at = ''
             OR c.enriched_at < datetime('now', '-7 days'))
        AND c.tcgdex_id NOT IN (SELECT tcgdex_id FROM cards
            ORDER BY COALESCE(top_price_eur, 0) + COALESCE(top_price_usd, 0) DESC LIMIT 5000)
        ORDER BY c.enriched_at ASC
        LIMIT 3000
    """).fetchall()

    # Combine and deduplicate
    seen = set()
    all_cards = []
    for r in list(top_cards) + list(stale_cards):
        if r["tcgdex_id"] not in seen:
            seen.add(r["tcgdex_id"])
            all_cards.append(r)

    # Budget check
    batch_size = 20
    max_batches = POKETRACE_DAILY_BUDGET // 2  # EU + US = 2 calls per batch
    max_cards = max_batches * batch_size
    all_cards = all_cards[:max_cards]

    est_requests = (len(all_cards) + batch_size - 1) // batch_size * 2
    print(f"  Cards to update: {len(all_cards)}")
    print(f"  Estimated requests: ~{est_requests}")

    if dry_run:
        print("  [DRY RUN] skipping")
        return

    # Build mapping
    cm_to_tcg = {str(r["cm_id_product"]): r["tcgdex_id"] for r in all_cards}
    cm_ids = list(cm_to_tcg.keys())

    matched = 0
    price_rows = 0

    for i in range(0, len(cm_ids), batch_size):
        if pt_calls >= POKETRACE_DAILY_BUDGET:
            print(f"  Budget exhausted at {pt_calls} calls")
            break

        batch = cm_ids[i:i + batch_size]
        batch_str = ",".join(batch)

        # EU market
        data = pt_get("/cards", {"cardmarket_ids": batch_str, "market": "EU"})
        if data and "data" in data:
            for card in data["data"]:
                cm_id = str(card.get("refs", {}).get("cardmarketId", ""))
                tcgdex_id = cm_to_tcg.get(cm_id)
                if not tcgdex_id:
                    continue
                prices = card.get("prices", {})
                for marketplace, tiers in prices.items():
                    if not isinstance(tiers, dict):
                        continue
                    for condition, tier in tiers.items():
                        if not isinstance(tier, dict):
                            continue
                        countries = tier.pop("country", None)
                        _save_price(conn, tcgdex_id, "poketrace", marketplace, condition, "ALL", "EUR", tier)
                        price_rows += 1
                        if countries and isinstance(countries, dict):
                            for cc, ct in countries.items():
                                if isinstance(ct, dict):
                                    _save_price(conn, tcgdex_id, "poketrace", marketplace, condition, cc, "EUR", ct)
                                    price_rows += 1

                # Update enriched_at
                top_eur = _best_price(prices, "cardmarket")
                conn.execute("""UPDATE cards SET top_price_eur = COALESCE(?, top_price_eur), enriched_at = ?
                                WHERE tcgdex_id = ?""", (top_eur, NOW, tcgdex_id))
                matched += 1

        # US market
        data_us = pt_get("/cards", {"cardmarket_ids": batch_str, "market": "US"})
        if data_us and "data" in data_us:
            for card in data_us["data"]:
                cm_id = str(card.get("refs", {}).get("cardmarketId", ""))
                tcgdex_id = cm_to_tcg.get(cm_id)
                if not tcgdex_id:
                    continue
                refs = card.get("refs", {})
                tcg_id = refs.get("tcgplayerId")
                if tcg_id:
                    conn.execute("UPDATE cards SET tcgplayer_id = ? WHERE tcgdex_id = ?", (tcg_id, tcgdex_id))
                prices = card.get("prices", {})
                for marketplace, tiers in prices.items():
                    if not isinstance(tiers, dict):
                        continue
                    for condition, tier in tiers.items():
                        if not isinstance(tier, dict):
                            continue
                        _save_price(conn, tcgdex_id, "poketrace", marketplace, condition, "ALL", "USD", tier)
                        price_rows += 1
                top_usd = _best_price(prices, "tcgplayer") or _best_price(prices, "ebay")
                if top_usd:
                    conn.execute("UPDATE cards SET top_price_usd = ? WHERE tcgdex_id = ?", (top_usd, tcgdex_id))

        if (i // batch_size + 1) % 100 == 0:
            conn.commit()
            print(f"  Progress: {i + batch_size}/{len(cm_ids)} | matched: {matched} | prices: {price_rows}")

    conn.commit()
    print(f"  Done: matched {matched} | price rows: {price_rows} | API calls: {pt_calls}")


def update_pokemon_api(conn, dry_run=False):
    """Update country-specific prices from Pokemon-API.com."""
    print("\n=== Pokemon-API Daily Update ===")

    # Fetch all episodes
    all_eps = []
    page = 1
    while True:
        data = pa_get("/episodes", {"page": page})
        if not data:
            break
        eps = data if isinstance(data, list) else data.get("data", [])
        if not eps:
            break
        all_eps.extend(eps)
        if len(eps) < 20:
            break
        page += 1

    print(f"  Episodes: {len(all_eps)}")

    # Build set mapping
    rows = conn.execute("SELECT set_id, abbreviation, name FROM sets WHERE language = 'en'").fetchall()
    set_map = {}
    for s in rows:
        norm = (s["abbreviation"] or "").strip().lower().replace(" ", "").replace("-", "").replace(".", "")
        if norm:
            set_map[norm] = s["set_id"]
        name_norm = (s["name"] or "").strip().lower().replace(" ", "").replace("-", "").replace(".", "")
        if name_norm and name_norm not in set_map:
            set_map[name_norm] = s["set_id"]

    # Match episodes to our sets
    matched_eps = []
    for ep in all_eps:
        code = (ep.get("code", "") or "").strip().lower().replace(" ", "").replace("-", "").replace(".", "")
        name = (ep.get("name", "") or "").strip().lower().replace(" ", "").replace("-", "").replace(".", "")
        slug = (ep.get("slug", "") or "").strip().lower().replace(" ", "").replace("-", "").replace(".", "")
        our_set = set_map.get(code) or set_map.get(name) or set_map.get(slug)
        if not our_set:
            for key, sid in set_map.items():
                if code and (code in key or key in code):
                    our_set = sid
                    break
        if our_set:
            matched_eps.append((ep, our_set))

    print(f"  Matched: {len(matched_eps)}/{len(all_eps)}")

    if dry_run:
        print("  [DRY RUN] skipping")
        return

    total_matched = 0
    total_prices = 0

    for idx, (ep, set_id) in enumerate(matched_eps):
        if pa_calls >= POKEMON_API_DAILY_BUDGET:
            print(f"  Budget exhausted at {pa_calls} calls")
            break

        cards_data = pa_get(f"/episodes/{ep['id']}/cards")
        if not cards_data:
            continue
        cards = cards_data if isinstance(cards_data, list) else cards_data.get("data", [])

        for card in cards:
            cn = card.get("card_number")
            if cn is None:
                continue

            tcgdex_id = None
            if isinstance(cn, int) or (isinstance(cn, str) and cn.isdigit()):
                row = conn.execute(
                    "SELECT tcgdex_id FROM cards WHERE set_id = ? AND collector_number = ? AND language = 'en'",
                    (set_id, int(cn))
                ).fetchone()
                if row:
                    tcgdex_id = row["tcgdex_id"]
            if not tcgdex_id:
                row = conn.execute(
                    "SELECT tcgdex_id FROM cards WHERE set_id = ? AND local_id = ? AND language = 'en'",
                    (set_id, str(cn))
                ).fetchone()
                if row:
                    tcgdex_id = row["tcgdex_id"]
            if not tcgdex_id:
                continue

            prices = card.get("prices", {})
            cm = prices.get("cardmarket", {})
            if cm and isinstance(cm, dict):
                if cm.get("lowest_near_mint"):
                    _save_price(conn, tcgdex_id, "pokemon_api", "cardmarket", "NEAR_MINT", "ALL", "EUR",
                                {"low": cm["lowest_near_mint"], "avg7d": cm.get("7d_average"), "avg30d": cm.get("30d_average")})
                    total_prices += 1
                for country in ["DE", "FR", "ES", "IT"]:
                    val = cm.get(f"lowest_near_mint_{country}")
                    if val:
                        _save_price(conn, tcgdex_id, "pokemon_api", "cardmarket", "NEAR_MINT", country, "EUR", {"low": val})
                        total_prices += 1

            tcg = prices.get("tcg_player", {})
            if tcg and isinstance(tcg, dict):
                market = tcg.get("market_price")
                if market:
                    _save_price(conn, tcgdex_id, "pokemon_api", "tcgplayer", "NEAR_MINT", "ALL", "USD", {"avg": market})
                    total_prices += 1

            total_matched += 1

        conn.commit()

    conn.commit()
    print(f"  Done: matched {total_matched} | price rows: {total_prices} | API calls: {pa_calls}")


def _save_price(conn, tcgdex_id, source, marketplace, condition, country, currency, tier):
    """Insert/replace a single price row."""
    conn.execute("""
        INSERT OR REPLACE INTO prices_external
        (tcgdex_id, source, marketplace, condition, country, currency,
         price_avg, price_low, price_high, price_trend,
         avg_1d, avg_7d, avg_30d, sale_count, confidence,
         snapshot_date, updated_at)
        VALUES (?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?)
    """, (
        tcgdex_id, source, marketplace, condition, country, currency,
        tier.get("avg"), tier.get("low"), tier.get("high"),
        tier.get("trend", ""),
        tier.get("avg1d"), tier.get("avg7d"), tier.get("avg30d"),
        tier.get("saleCount"), tier.get("confidence", ""),
        TODAY, NOW,
    ))


def _best_price(prices, marketplace):
    """Get best price from a marketplace."""
    mp = prices.get(marketplace, {})
    if not isinstance(mp, dict):
        return None
    for cond in ["AGGREGATED", "NEAR_MINT"]:
        tier = mp.get(cond, {})
        if isinstance(tier, dict) and tier.get("avg"):
            return tier["avg"]
    return None


def main():
    parser = argparse.ArgumentParser(description="Daily price update")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--poketrace-only", action="store_true")
    parser.add_argument("--pokemon-api-only", action="store_true")
    args = parser.parse_args()

    print(f"Daily Price Update | {TODAY}")
    conn = ensure_schema()

    # Stats before
    pe = conn.execute("SELECT COUNT(*) FROM prices_external").fetchone()[0]
    print(f"  Price rows before: {pe}")

    t0 = time.time()

    if not args.pokemon_api_only:
        if POKETRACE_API_KEY:
            update_poketrace(conn, dry_run=args.dry_run)
        else:
            print("  [SKIP] POKETRACE_API_KEY not set")

    if not args.poketrace_only:
        if POKEMON_API_RAPIDAPI_KEY:
            update_pokemon_api(conn, dry_run=args.dry_run)
        else:
            print("  [SKIP] POKEMON_API_RAPIDAPI_KEY not set")

    elapsed = time.time() - t0

    # Stats after
    pe_after = conn.execute("SELECT COUNT(*) FROM prices_external").fetchone()[0]
    print(f"\n=== Daily Update Complete in {elapsed:.0f}s ===")
    print(f"  Price rows: {pe} -> {pe_after} (+{pe_after - pe})")
    print(f"  PokeTrace calls: {pt_calls}")
    print(f"  Pokemon-API calls: {pa_calls}")

    conn.close()


if __name__ == "__main__":
    main()
