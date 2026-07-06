"""Refresh the local `prices` table from CardMarket's PUBLIC daily Pokemon price guide.

CardMarket publishes each game's price guide as a public JSON file (no login, no
API key) linked from https://www.cardmarket.com/en/Pokemon/Data/Price-Guide. The
"Pokemon price guide" button points at ONE file (currently price_guide_6.json,
~15 MB) that covers 100% of our cm_id_products across EN/JP/TW. Each entry is keyed
by `idProduct` == our `cards.cm_id_product`, so we join directly.

This keeps the `prices` table (scan headline + the /prices CardMarket fallback)
fresh for ALL languages incl. JP/TW, which PokeTrace's EU feed covers poorly.
Updated daily by CardMarket (see each file's `createdAt`).

Usage:
    python scripts/refresh_cardmarket_priceguide.py --db data/cards.db
    python scripts/refresh_cardmarket_priceguide.py --db /app/data/cards.db   # prod
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
import urllib.request
from datetime import datetime, timezone

PAGE = "https://www.cardmarket.com/en/Pokemon/Data/Price-Guide"
S3 = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_{n}.json"
FALLBACK_SHARD = 6           # the Pokemon shard as of 2026-07
POKEMON_CATEGORY = 51        # idCategory for Pokemon singles (sanity check)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def _get(url: str, retries: int = 4) -> bytes | None:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                if r.status == 200:
                    return r.read()
        except Exception as e:
            if getattr(e, "code", None) == 404:
                return None
            time.sleep(2 * (attempt + 1))
    return None


def resolve_pokemon_url() -> str:
    """Scrape the Price-Guide page for the 'Pokemon price guide' link; fall back
    to the known shard. Keeps working if CardMarket renumbers the shard."""
    html = _get(PAGE)
    if html:
        # anchor: href="...price_guide_N.json"> ... Pokémon price guide
        m = re.search(
            r'href="(https://downloads\.s3\.cardmarket\.com/productCatalog/priceGuide/price_guide_\d+\.json)"'
            r'[^>]*>(?:(?!</a>).)*?Pok[eé]mon price guide',
            html.decode("utf-8", "ignore"), re.I | re.S)
        if m:
            return m.group(1)
        print("  [warn] could not locate Pokemon link on page; using fallback shard")
    else:
        print("  [warn] price-guide page fetch failed; using fallback shard")
    return S3.format(n=FALLBACK_SHARD)


def load_guide() -> dict[int, dict]:
    url = resolve_pokemon_url()
    print(f"Pokemon price guide: {url}")
    raw = _get(url)
    if not raw:
        raise SystemExit("Failed to download the price guide — aborting (prices untouched).")
    data = json.loads(raw)
    guides = data.get("priceGuides", [])
    print(f"Downloaded {len(guides)} entries (createdAt {data.get('createdAt')})")
    # sanity: this must be the Pokemon file, not some other game's
    cats = {}
    for g in guides:
        cats[g.get("idCategory")] = cats.get(g.get("idCategory"), 0) + 1
    if cats.get(POKEMON_CATEGORY, 0) < 10000:
        raise SystemExit(
            f"Sanity check failed: idCategory {POKEMON_CATEGORY} only {cats.get(POKEMON_CATEGORY,0)} "
            f"entries — wrong file? cats={dict(list(cats.items())[:8])}. Aborting.")
    return {g["idProduct"]: g for g in guides if g.get("idProduct") is not None}


def refresh(db_path: str, dry_run: bool = False) -> None:
    guide = load_guide()
    now = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    our = {r["cm_id_product"]: r["name"] for r in con.execute(
        "SELECT DISTINCT cm_id_product, name FROM cards WHERE cm_id_product > 0")}
    existing = {r[0] for r in con.execute("SELECT cm_id_product FROM prices")}
    print(f"Our catalog: {len(our)} distinct cm_id_products; {len(existing)} already in prices")

    updated = inserted = matched = 0
    for pid, name in our.items():
        g = guide.get(pid)
        if not g:
            continue
        matched += 1
        if dry_run:
            continue
        vals = (
            g.get("avg") or 0, g.get("low") or 0, g.get("trend") or 0,
            g.get("avg1") or 0, g.get("avg7") or 0, g.get("avg30") or 0,
            g.get("trend-holo") or 0, g.get("low-holo") or 0, now,
        )
        if pid in existing:
            con.execute(
                "UPDATE prices SET avg=?, low=?, trend=?, avg1=?, avg7=?, avg30=?, "
                "foil_trend=?, foil_low=?, updated_at=? WHERE cm_id_product=?", (*vals, pid))
            updated += 1
        else:
            con.execute(
                "INSERT INTO prices (cm_id_product, cm_name, cm_expansion_id, avg, low, trend, "
                "avg1, avg7, avg30, foil_trend, foil_low, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, name or "", None,
                 g.get("avg") or 0, g.get("low") or 0, g.get("trend") or 0,
                 g.get("avg1") or 0, g.get("avg7") or 0, g.get("avg30") or 0,
                 g.get("trend-holo") or 0, g.get("low-holo") or 0, now))
            inserted += 1
    if not dry_run:
        con.commit()
    print(f"Matched {matched}/{len(our)} of our products in the guide")
    print(f"{'[DRY] would ' if dry_run else ''}updated={updated} inserted={inserted}")
    con.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/cards.db")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    refresh(a.db, a.dry_run)


if __name__ == "__main__":
    main()
