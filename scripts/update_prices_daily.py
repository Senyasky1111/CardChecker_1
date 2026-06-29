"""
Daily price update script.

Refreshes ALL card prices from PokeTrace, Pokemon-API, and CardMarket CSV.
Updates every card in the database — no prioritization needed since we fit
within daily API limits (~6.5K PokeTrace + ~170 Pokemon-API requests).

Usage:
    python scripts/update_prices_daily.py [--dry-run] [--poketrace-only] [--pokemon-api-only] [--csv-only]

Schedule (Windows Task Scheduler or cron):
    # Daily at 6:00 AM
    0 6 * * * cd /path/to/CardRecognition && ./venv/Scripts/python.exe scripts/update_prices_daily.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import io
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import (
    POKETRACE_API_KEY, POKETRACE_BASE_URL, POKETRACE_BURST_DELAY,
    POKEMON_API_RAPIDAPI_KEY, POKEMON_API_DELAY,
)
from src.db import ensure_schema

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
NOW = datetime.now(timezone.utc).isoformat()

# Safety limits (hard stop if exceeded). Override via env to cover ALL cards
# across multiple runs or with a higher daily quota:
#   PT_LIMIT=20000 PA_LIMIT=5000 python scripts/update_prices_daily.py
# Default PokeTrace cap of 9500 fits a 10K/day plan with a 500 buffer; with
# ~43K CM cards (EU) + ~18K tcgplayer cards (US) batched at 20/req the full
# sweep needs ~3K requests, so a single run already covers everything — but
# raise PT_LIMIT if the plan quota is lower and you want explicit headroom.
PT_LIMIT = int(os.getenv("PT_LIMIT", "9500"))   # PokeTrace daily call cap
PA_LIMIT = int(os.getenv("PA_LIMIT", "3000"))   # Pokemon-API daily call cap

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
pt_consecutive_429 = 0
PT_429_ABORT = 5  # Stop after 5 consecutive 429s (quota clearly exhausted)


def pt_get(endpoint, params=None, retries=3):
    """PokeTrace GET with rate limit."""
    global pt_calls, pt_consecutive_429
    if pt_calls >= PT_LIMIT or pt_consecutive_429 >= PT_429_ABORT:
        return None
    for attempt in range(retries):
        try:
            time.sleep(POKETRACE_BURST_DELAY)
            r = pt_session.get(f"{POKETRACE_BASE_URL}{endpoint}", params=params, timeout=15)
            pt_calls += 1
            if r.status_code == 200:
                pt_consecutive_429 = 0
                return r.json()
            elif r.status_code == 429:
                pt_consecutive_429 += 1
                if pt_consecutive_429 >= PT_429_ABORT:
                    print(f"  [PT 429] Quota exhausted ({pt_consecutive_429} consecutive 429s). Stopping PokeTrace.")
                    return None
                wait = int(r.headers.get("Retry-After", 10))
                print(f"  [PT 429] waiting {wait}s...")
                time.sleep(wait)
                continue
            else:
                pt_consecutive_429 = 0
                return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


def pa_get(endpoint, params=None, retries=3):
    """Pokemon-API GET with rate limit."""
    global pa_calls
    if pa_calls >= PA_LIMIT:
        return None
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


# ── Step 1: PokeTrace Bulk — ALL cards with cm_id_product ────────────

def update_poketrace_bulk(conn, dry_run=False):
    """Refresh prices for ALL cards that have cm_id_product via bulk lookup."""
    print("\n=== Step 1: PokeTrace Bulk — ALL cards with CM ID ===")

    all_cards = conn.execute("""
        SELECT tcgdex_id, cm_id_product FROM cards
        WHERE cm_id_product IS NOT NULL AND cm_id_product > 0
        ORDER BY cm_id_product
    """).fetchall()

    batch_size = 20
    est_requests = (len(all_cards) + batch_size - 1) // batch_size  # EU only (US is a separate step)
    print(f"  Cards: {len(all_cards)}")
    print(f"  Estimated requests: ~{est_requests}")

    if dry_run:
        print("  [DRY RUN] skipping")
        return

    cm_to_tcg = {str(r["cm_id_product"]): r["tcgdex_id"] for r in all_cards}
    cm_ids = list(cm_to_tcg.keys())
    matched = 0
    price_rows = 0

    for i in range(0, len(cm_ids), batch_size):
        if pt_calls >= PT_LIMIT or pt_consecutive_429 >= PT_429_ABORT:
            print(f"  API limit reached at {pt_calls} calls")
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
                prices = card.get("prices") or {}
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

                top_eur = _best_price(prices, "cardmarket")
                has_graded = 1 if any(
                    cond.startswith(("PSA_", "BGS_", "CGC_", "SGC_"))
                    for mp_tiers in prices.values() if isinstance(mp_tiers, dict)
                    for cond in mp_tiers.keys()
                ) else 0
                conn.execute("""UPDATE cards SET
                    top_price_eur = COALESCE(?, top_price_eur),
                    has_graded = ?,
                    enriched_at = ?
                    WHERE tcgdex_id = ?""", (top_eur, has_graded, NOW, tcgdex_id))
                matched += 1

        # NOTE: US prices are NOT fetched here. PokeTrace's /cards?market=US
        # endpoint is keyed by tcgplayer_ids, NOT cardmarket_ids — querying it
        # with cardmarket_ids returns an empty data array (verified against
        # base1-1 / cm 273696). US/TCGplayer+eBay ingestion lives in
        # update_poketrace_us() below, driven by cards.tcgplayer_id.

        batch_num = i // batch_size + 1
        total_batches = (len(cm_ids) + batch_size - 1) // batch_size
        if batch_num % 100 == 0 or batch_num == total_batches:
            conn.commit()
            print(f"  Progress: {min(i + batch_size, len(cm_ids))}/{len(cm_ids)} | matched: {matched} | prices: {price_rows} | API: {pt_calls}")

    conn.commit()
    print(f"  Done: matched {matched}/{len(all_cards)} | price rows: {price_rows} | API calls: {pt_calls}")


# ── Step 1b: PokeTrace US — ALL cards with tcgplayer_id ──────────────

def update_poketrace_us(conn, dry_run=False, only_tcgplayer_ids=None):
    """Refresh US (TCGplayer + eBay) prices for ALL cards with a tcgplayer_id.

    PokeTrace's US market is keyed by tcgplayer_ids (NOT cardmarket_ids). The
    response keys each card by refs.tcgplayerId and exposes 'tcgplayer' and
    'ebay' marketplaces with full condition tiers (NEAR_MINT, LIGHTLY_PLAYED,
    graded, etc.). Verified working against base1-1 (tcgplayer_id 42346).

    only_tcgplayer_ids: optional iterable of tcgplayer_id values to restrict
    the run to (used for small validation samples). When None, all cards with
    a tcgplayer_id are processed.
    """
    print("\n=== Step 1b: PokeTrace US — ALL cards with tcgplayer_id ===")

    rows = conn.execute("""
        SELECT tcgdex_id, tcgplayer_id FROM cards
        WHERE tcgplayer_id IS NOT NULL AND tcgplayer_id != ''
        ORDER BY tcgplayer_id
    """).fetchall()

    # Multiple cards (e.g. EN reprints) can share one tcgplayer_id, so map
    # tcgplayer_id -> [tcgdex_id, ...] and fan the prices out to all of them.
    tcg_to_cards = {}
    for r in rows:
        tid = str(r["tcgplayer_id"]).strip()
        if not tid:
            continue
        if only_tcgplayer_ids is not None and tid not in only_tcgplayer_ids:
            continue
        tcg_to_cards.setdefault(tid, []).append(r["tcgdex_id"])

    tcg_ids = list(tcg_to_cards.keys())
    batch_size = 20
    print(f"  Cards with tcgplayer_id: {sum(len(v) for v in tcg_to_cards.values())} "
          f"({len(tcg_ids)} unique tcgplayer_ids)")
    print(f"  Estimated requests: ~{(len(tcg_ids) + batch_size - 1) // batch_size}")

    if dry_run:
        print("  [DRY RUN] skipping")
        return 0

    matched = 0
    price_rows = 0

    for i in range(0, len(tcg_ids), batch_size):
        if pt_calls >= PT_LIMIT or pt_consecutive_429 >= PT_429_ABORT:
            print(f"  API limit reached at {pt_calls} calls")
            break

        batch = tcg_ids[i:i + batch_size]
        batch_str = ",".join(batch)

        data_us = pt_get("/cards", {"tcgplayer_ids": batch_str, "market": "US"})
        if data_us and "data" in data_us:
            for card in data_us["data"]:
                tcg_id = str(card.get("refs", {}).get("tcgplayerId", "")).strip()
                tcgdex_ids = tcg_to_cards.get(tcg_id)
                if not tcgdex_ids:
                    continue
                prices = card.get("prices") or {}
                top_usd = _best_price(prices, "tcgplayer") or _best_price(prices, "ebay")
                for tcgdex_id in tcgdex_ids:
                    for marketplace, tiers in prices.items():
                        if not isinstance(tiers, dict):
                            continue
                        for condition, tier in tiers.items():
                            if not isinstance(tier, dict):
                                continue
                            _save_price(conn, tcgdex_id, "poketrace", marketplace,
                                        condition, "ALL", "USD", tier)
                            price_rows += 1
                    if top_usd:
                        conn.execute(
                            "UPDATE cards SET top_price_usd = ? WHERE tcgdex_id = ?",
                            (top_usd, tcgdex_id))
                    matched += 1

        batch_num = i // batch_size + 1
        total_batches = (len(tcg_ids) + batch_size - 1) // batch_size
        if batch_num % 100 == 0 or batch_num == total_batches:
            conn.commit()
            print(f"  Progress: {min(i + batch_size, len(tcg_ids))}/{len(tcg_ids)} "
                  f"unique ids | matched: {matched} | prices: {price_rows} | API: {pt_calls}")

    conn.commit()
    print(f"  Done: matched {matched} cards | price rows: {price_rows} | API calls: {pt_calls}")
    return price_rows


# ── Step 2: PokeTrace Search — ALL cards WITHOUT cm_id_product ───────

def update_poketrace_search(conn, dry_run=False):
    """Refresh prices for ALL cards without cm_id_product via search."""
    print("\n=== Step 2: PokeTrace Search — ALL cards without CM ID ===")

    cards = conn.execute("""
        SELECT c.tcgdex_id, c.name, c.eng_name, c.collector_number, c.language, c.set_id
        FROM cards c
        WHERE (c.cm_id_product IS NULL OR c.cm_id_product = 0)
        AND c.eng_name IS NOT NULL AND c.eng_name != ''
        ORDER BY c.language, c.set_id, c.collector_number
    """).fetchall()

    print(f"  Cards: {len(cards)}")
    print(f"  Estimated requests: ~{len(cards)}")

    if dry_run:
        print("  [DRY RUN] skipping")
        return

    matched = 0
    price_rows = 0
    new_cm_ids = 0

    for idx, card in enumerate(cards):
        if pt_calls >= PT_LIMIT or pt_consecutive_429 >= PT_429_ABORT:
            print(f"  API limit reached at {pt_calls} calls")
            break

        lang = card["language"]
        game = "pokemon-japanese" if lang in ("ja", "zh-tw") else "pokemon"
        params = {"game": game, "search": card["eng_name"], "limit": 5}
        if card["collector_number"]:
            params["card_number"] = str(card["collector_number"])

        data = pt_get("/cards", params)
        if not data or "data" not in data or not data["data"]:
            continue

        # Match by card number
        best = None
        for api_card in data["data"]:
            card_num = api_card.get("cardNumber", "")
            if card_num and card["collector_number"] and str(card["collector_number"]) in str(card_num):
                best = api_card
                break
        if not best:
            best = data["data"][0]

        # Save prices
        prices = best.get("prices") or {}
        for marketplace, tiers in prices.items():
            if not isinstance(tiers, dict):
                continue
            for condition, tier in tiers.items():
                if not isinstance(tier, dict):
                    continue
                countries = tier.pop("country", None)
                _save_price(conn, card["tcgdex_id"], "poketrace", marketplace, condition, "ALL", "EUR", tier)
                price_rows += 1
                if countries and isinstance(countries, dict):
                    for cc, ct in countries.items():
                        if isinstance(ct, dict):
                            _save_price(conn, card["tcgdex_id"], "poketrace", marketplace, condition, cc, "EUR", ct)
                            price_rows += 1

        top_eur = _best_price(prices, "cardmarket")
        top_usd = _best_price(prices, "tcgplayer") or _best_price(prices, "ebay")
        conn.execute("""UPDATE cards SET
            top_price_eur = COALESCE(?, top_price_eur),
            top_price_usd = COALESCE(?, top_price_usd),
            enriched_at = ? WHERE tcgdex_id = ?""",
            (top_eur, top_usd, NOW, card["tcgdex_id"]))

        # Fill cm_id_product if found — check for duplicates first
        cm_id = best.get("refs", {}).get("cardmarketId")
        if cm_id:
            existing = conn.execute(
                "SELECT tcgdex_id FROM cards WHERE cm_id_product = ? AND set_id = ? AND language = ?",
                (cm_id, card["set_id"], card["language"])
            ).fetchone()
            if not existing:
                conn.execute("UPDATE cards SET cm_id_product = ? WHERE tcgdex_id = ?",
                             (cm_id, card["tcgdex_id"]))
                new_cm_ids += 1

        matched += 1

        if (idx + 1) % 200 == 0:
            conn.commit()
            print(f"  Progress: {idx + 1}/{len(cards)} | matched: {matched} | new CM IDs: {new_cm_ids} | API: {pt_calls}")

    conn.commit()
    print(f"  Done: matched {matched}/{len(cards)} | price rows: {price_rows} | new CM IDs: {new_cm_ids}")


# ── Step 3: Pokemon-API — ALL episodes ───────────────────────────────

def update_pokemon_api(conn, dry_run=False):
    """Update country-specific prices from Pokemon-API.com for ALL sets."""
    print("\n=== Step 3: Pokemon-API — ALL episodes ===")

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
        if pa_calls >= PA_LIMIT:
            print(f"  API limit reached at {pa_calls} calls")
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

            prices = card.get("prices") or {}
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

            # Graded prices
            psa = prices.get("psa", {})
            if psa and isinstance(psa, dict):
                for grade_key, grade_cond in [("psa10", "PSA_10"), ("psa9", "PSA_9")]:
                    val = psa.get(grade_key)
                    if val:
                        _save_price(conn, tcgdex_id, "pokemon_api", "cardmarket", grade_cond, "ALL", "EUR", {"avg": val})
                        total_prices += 1

            cgc = prices.get("cgc", {})
            if cgc and isinstance(cgc, dict):
                val = cgc.get("cgc10")
                if val:
                    _save_price(conn, tcgdex_id, "pokemon_api", "cardmarket", "CGC_10", "ALL", "EUR", {"avg": val})
                    total_prices += 1

            total_matched += 1

        conn.commit()

    conn.commit()
    print(f"  Done: matched {total_matched} | price rows: {total_prices} | API calls: {pa_calls}")


# ── Step 4: CardMarket CSV Refresh ───────────────────────────────────

def update_from_csv(conn, dry_run=False):
    """Refresh prices from CardMarket CSV if a recent file exists."""
    print("\n=== Step 4: CardMarket CSV Refresh ===")

    csv_path = Path("data/cardmarket/cards_with_prices.json")
    if not csv_path.exists():
        print("  [SKIP] cards_with_prices.json not found")
        return

    mtime = datetime.fromtimestamp(os.path.getmtime(csv_path), tz=timezone.utc)
    age_days = (datetime.now(timezone.utc) - mtime).days
    print(f"  CSV file age: {age_days} days (modified: {mtime.strftime('%Y-%m-%d %H:%M')})")

    if age_days > 30:
        print("  [SKIP] CSV too old (>30 days). Download fresh from CardMarket.")
        return

    with open(csv_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    products = data["cards"]
    by_id = {p["id_product"]: p for p in products}
    print(f"  CSV products: {len(by_id)}")

    if dry_run:
        print("  [DRY RUN] skipping")
        return

    # Update ALL EN cards with cm_id from CSV
    cards = conn.execute("""
        SELECT tcgdex_id, cm_id_product FROM cards
        WHERE cm_id_product IS NOT NULL AND cm_id_product > 0
        AND language = 'en'
    """).fetchall()

    updated = 0
    for card in cards:
        p = by_id.get(card["cm_id_product"])
        if not p:
            continue

        trend = p.get("price_trend") or 0
        avg = p.get("price_avg") or 0
        low = p.get("price_low") or 0
        best_price = trend or avg or low
        if best_price <= 0:
            continue

        conn.execute("""
            INSERT OR REPLACE INTO prices_external
            (tcgdex_id, source, marketplace, condition, country, currency,
             price_avg, price_low, price_trend, avg_7d, avg_30d,
             snapshot_date, updated_at)
            VALUES (?, 'cardmarket_csv', 'cardmarket', 'AGGREGATED', 'ALL', 'EUR',
                    ?, ?, ?, ?, ?, ?, ?)
        """, (
            card["tcgdex_id"],
            avg or None, low or None, str(trend) if trend else "",
            p.get("price_avg7"), p.get("price_avg30"),
            TODAY, NOW,
        ))

        # Foil prices
        foil_trend = p.get("price_foil_trend") or 0
        foil_low = p.get("price_foil_low") or 0
        if foil_trend > 0 or foil_low > 0:
            conn.execute("""
                INSERT OR REPLACE INTO prices_external
                (tcgdex_id, source, marketplace, condition, country, currency,
                 price_avg, price_low, price_trend,
                 snapshot_date, updated_at)
                VALUES (?, 'cardmarket_csv', 'cardmarket', 'FOIL', 'ALL', 'EUR',
                        NULL, ?, ?, ?, ?)
            """, (
                card["tcgdex_id"],
                foil_low or None, str(foil_trend) if foil_trend else "",
                TODAY, NOW,
            ))

        # Fill top_price_eur if missing
        conn.execute("""
            UPDATE cards SET top_price_eur = ?
            WHERE tcgdex_id = ? AND (top_price_eur IS NULL OR top_price_eur = 0)
        """, (best_price, card["tcgdex_id"]))

        updated += 1

    conn.commit()
    print(f"  Updated: {updated} cards from CSV")


# ── Helpers ──────────────────────────────────────────────────────────

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


def _print_stats(conn, label=""):
    """Print current DB stats."""
    if label:
        print(f"\n=== {label} ===")
    for lang, lbl in [("en", "EN"), ("ja", "JP"), ("zh-tw", "TW")]:
        total = conn.execute("SELECT COUNT(*) FROM cards WHERE language=?", (lang,)).fetchone()[0]
        has_eur = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND top_price_eur > 0", (lang,)).fetchone()[0]
        has_usd = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND top_price_usd > 0", (lang,)).fetchone()[0]
        with_cm = conn.execute("SELECT COUNT(*) FROM cards WHERE language=? AND cm_id_product IS NOT NULL AND cm_id_product > 0", (lang,)).fetchone()[0]
        print(f"  {lbl}: {total} total | EUR: {has_eur} ({100*has_eur/total:.0f}%) | USD: {has_usd} | CM: {with_cm}")

    pe = conn.execute("SELECT COUNT(*) FROM prices_external").fetchone()[0]
    print(f"  prices_external: {pe} rows")


# ── Step 5: Fix PriceCharting URLs ────────────────────────────────────

def _fix_pricecharting_urls(conn):
    """Regenerate PriceCharting search URLs for JP/TW cards.

    Removes stale abbreviation codes (M1L, SV5K) that PriceCharting doesn't
    recognize, and ensures correct language tag (japanese/chinese).
    """
    import re as _re
    from urllib.parse import quote_plus

    PC_BASE = "https://www.pricecharting.com"
    fixed = 0

    rows = conn.execute("""
        SELECT tcgdex_id, name, eng_name, language, set_id, collector_number, pricecharting_url
        FROM cards WHERE language IN ('ja', 'zh-tw')
    """).fetchall()

    print(f"\n=== Step 5: Fix PriceCharting URLs ({len(rows)} JP/TW cards) ===")

    for tcgdex_id, name, eng_name, lang, set_id, collector_number, old_url in rows:
        card_name = (eng_name or name or "").strip()
        if not card_name:
            continue

        clean = _re.sub(r"\s*\[.*?\]", "", card_name)
        clean = _re.sub(r"\s*\(.*?\)", "", clean).strip()
        parts = [clean]

        if collector_number is not None:
            try:
                parts.append(str(int(collector_number)))
            except (ValueError, TypeError):
                pass

        parts.append("japanese" if lang == "ja" else "chinese")
        query = " ".join(parts)
        new_url = f"{PC_BASE}/search-products?q={quote_plus(query)}&type=prices"

        if new_url != (old_url or "").strip():
            conn.execute("UPDATE cards SET pricecharting_url = ? WHERE tcgdex_id = ?",
                         (new_url, tcgdex_id))
            fixed += 1

    conn.commit()
    print(f"  Fixed {fixed}/{len(rows)} PriceCharting URLs")


# ── Step 6: PokeTrace Price History ──────────────────────────────────

def update_price_history(conn, dry_run=False, max_cards=1000):
    """Fetch deep price history from PokeTrace for high-value cards.

    Uses GET /v1/cards/{poketrace_id}/prices/{tier}/history?period=90d
    Available on Pro tier. One call per card, returns daily time series.

    Only fetches cards with top_price_eur > 3 that haven't been fetched
    in the last 7 days, up to max_cards per run.
    """
    print(f"\n=== Step 6: PokeTrace Price History (max {max_cards} cards) ===")

    if dry_run:
        print("  [DRY RUN] skipping")
        return

    # Create table if not exists (for old DBs without migration)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS price_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tcgdex_id   TEXT NOT NULL,
            marketplace TEXT NOT NULL,
            condition   TEXT NOT NULL,
            date        TEXT NOT NULL,
            avg         REAL,
            low         REAL,
            high        REAL,
            sale_count  INTEGER,
            median_7d   REAL,
            median_30d  REAL,
            source      TEXT DEFAULT 'poketrace',
            UNIQUE(tcgdex_id, marketplace, condition, date)
        );
        CREATE INDEX IF NOT EXISTS idx_ph_card ON price_history(tcgdex_id);
    """)

    # Find high-value cards with PokeTrace IDs, not fetched recently
    cards = conn.execute("""
        SELECT e.tcgdex_id, e.poketrace_id
        FROM card_external_ids e
        JOIN cards c ON c.tcgdex_id = e.tcgdex_id
        WHERE e.poketrace_id IS NOT NULL
              AND e.poketrace_id != ''
              AND (c.top_price_eur > 3 OR c.top_price_usd > 3)
              AND e.tcgdex_id NOT IN (
                  SELECT DISTINCT tcgdex_id FROM price_history
                  WHERE date >= date('now', '-7 days')
              )
        ORDER BY COALESCE(c.top_price_eur, 0) + COALESCE(c.top_price_usd, 0) DESC
        LIMIT ?
    """, (max_cards,)).fetchall()

    print(f"  Cards to fetch: {len(cards)}")
    fetched = 0
    rows_added = 0

    for card in cards:
        if pt_calls >= PT_LIMIT or pt_consecutive_429 >= PT_429_ABORT:
            print(f"  API limit reached at {pt_calls} calls")
            break

        pt_id = card["poketrace_id"]
        tcgdex_id = card["tcgdex_id"]

        # Fetch EU market history (CardMarket + eBay)
        data = pt_get(f"/cards/{pt_id}/prices/EU/history", {"period": "90d"})
        if data and "data" in data:
            for point in data["data"]:
                date_str = (point.get("date") or "")[:10]
                if not date_str:
                    continue
                source_mp = (point.get("source") or "").lower()
                # Map PokeTrace source names to our marketplace names
                mp = source_mp if source_mp in ("cardmarket", "ebay") else source_mp
                if not mp:
                    continue
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO price_history
                        (tcgdex_id, marketplace, condition, date, avg, low, high,
                         sale_count, median_7d, median_30d, source)
                        VALUES (?, ?, 'AGGREGATED', ?, ?, ?, ?, ?, ?, ?, 'poketrace')
                    """, (
                        tcgdex_id, mp, date_str,
                        point.get("avg"), point.get("low"), point.get("high"),
                        point.get("saleCount"), point.get("median3d"), point.get("median7d"),
                    ))
                    rows_added += 1
                except Exception:
                    pass

        # Fetch US market history (TCGPlayer + eBay)
        data_us = pt_get(f"/cards/{pt_id}/prices/US/history", {"period": "90d"})
        if data_us and "data" in data_us:
            for point in data_us["data"]:
                date_str = (point.get("date") or "")[:10]
                if not date_str:
                    continue
                source_mp = (point.get("source") or "").lower()
                mp = source_mp if source_mp in ("tcgplayer", "ebay") else source_mp
                if not mp:
                    continue
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO price_history
                        (tcgdex_id, marketplace, condition, date, avg, low, high,
                         sale_count, median_7d, median_30d, source)
                        VALUES (?, ?, 'AGGREGATED', ?, ?, ?, ?, ?, ?, ?, 'poketrace')
                    """, (
                        tcgdex_id, mp, date_str,
                        point.get("avg"), point.get("low"), point.get("high"),
                        point.get("saleCount"), point.get("median3d"), point.get("median7d"),
                    ))
                    rows_added += 1
                except Exception:
                    pass

        fetched += 1
        if fetched % 50 == 0:
            conn.commit()
            print(f"  Progress: {fetched}/{len(cards)} cards, {rows_added} rows added")

    conn.commit()
    print(f"  Done: {fetched} cards fetched, {rows_added} history rows added")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Daily price update — ALL cards")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--poketrace-only", action="store_true")
    parser.add_argument("--pokemon-api-only", action="store_true")
    parser.add_argument("--csv-only", action="store_true")
    args = parser.parse_args()

    run_all = not (args.poketrace_only or args.pokemon_api_only or args.csv_only)

    print(f"=== Daily Price Update | {TODAY} ===")
    conn = ensure_schema()
    _print_stats(conn, "Before")

    t0 = time.time()

    # Step 1: PokeTrace Bulk EU (all cards with cm_id)
    if (run_all or args.poketrace_only) and POKETRACE_API_KEY:
        update_poketrace_bulk(conn, dry_run=args.dry_run)
    elif run_all and not POKETRACE_API_KEY:
        print("\n  [SKIP] POKETRACE_API_KEY not set")

    # Step 1b: PokeTrace US (all cards with tcgplayer_id → TCGplayer + eBay)
    if (run_all or args.poketrace_only) and POKETRACE_API_KEY:
        update_poketrace_us(conn, dry_run=args.dry_run)

    # Step 2: PokeTrace Search (all cards without cm_id)
    if (run_all or args.poketrace_only) and POKETRACE_API_KEY:
        update_poketrace_search(conn, dry_run=args.dry_run)

    # Step 3: Pokemon-API (all episodes)
    if (run_all or args.pokemon_api_only) and POKEMON_API_RAPIDAPI_KEY:
        update_pokemon_api(conn, dry_run=args.dry_run)
    elif run_all and not POKEMON_API_RAPIDAPI_KEY:
        print("\n  [SKIP] POKEMON_API_RAPIDAPI_KEY not set")

    # Step 4: CSV Refresh
    if run_all or args.csv_only:
        update_from_csv(conn, dry_run=args.dry_run)

    # Step 5: Regenerate PriceCharting URLs for JP/TW (remove stale abbreviation codes)
    if run_all and not args.dry_run:
        _fix_pricecharting_urls(conn)

    # Step 6: PokeTrace Price History (deep time series for high-value cards)
    if (run_all or args.poketrace_only) and POKETRACE_API_KEY and not args.csv_only:
        update_price_history(conn, dry_run=args.dry_run)

    elapsed = time.time() - t0

    _print_stats(conn, "After")
    print(f"\n=== Complete in {elapsed:.0f}s | PT: {pt_calls} calls | PA: {pa_calls} calls ===")

    # Log run
    if not args.dry_run:
        conn.execute("""
            INSERT INTO enrichment_runs (phase, started_at, completed_at, cards_processed, status)
            VALUES ('daily_update', ?, ?, ?, 'completed')
        """, (datetime.fromtimestamp(t0, tz=timezone.utc).isoformat(), NOW, pt_calls + pa_calls))
        conn.commit()

    conn.close()


if __name__ == "__main__":
    main()
