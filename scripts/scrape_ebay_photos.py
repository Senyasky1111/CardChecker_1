"""
Scrape real card photos from eBay listings for CLIP fine-tuning dataset.

Uses Apify's eBay scraper (headless browser + proxy) to bypass anti-bot.

Strategy:
  1. Query our DB for cards (name + collector number + set)
  2. Search eBay via Apify actor (handles JS rendering + captcha)
  3. Download seller photos (real-world photos)
  4. Save as training pairs: (photo_path, tcgdex_id)

Requires: APIFY_TOKEN env var or --token flag.

Usage:
    python scripts/scrape_ebay_photos.py --token YOUR_TOKEN
    python scripts/scrape_ebay_photos.py --cards 500 --per-card 5
    python scripts/scrape_ebay_photos.py --resume
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote_plus

import requests
from tqdm import tqdm

# ---------- Config ----------

OUTPUT_DIR = Path("data/training_photos")
PAIRS_FILE = OUTPUT_DIR / "pairs.jsonl"
DB_PATH = Path("data/cards.db")

APIFY_ACTOR = "PBSxkfoBWghbE2set"  # dtrungtin/ebay-items-scraper
APIFY_API = "https://api.apify.com/v2"


# ---------- DB ----------

def load_cards(
    db_path: Path,
    lang: str | None = None,
    set_id: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """Load random cards from DB for scraping. Prioritizes cards with prices."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    sql = """
        SELECT c.tcgdex_id, c.name, c.eng_name, c.collector_number,
               c.set_total, c.language, c.rarity, c.image_url,
               s.name AS set_name, s.abbreviation
        FROM cards c
        JOIN sets s ON c.set_id = s.set_id AND s.language = c.language
        LEFT JOIN prices p ON c.cm_id_product = p.cm_id_product
        WHERE c.collector_number IS NOT NULL
          AND c.name IS NOT NULL
    """
    params: list = []

    if lang:
        sql += " AND c.language = ?"
        params.append(lang)
    if set_id:
        sql += " AND c.set_id = ?"
        params.append(set_id)

    # Prioritize cards with prices (more popular = more eBay listings)
    sql += " ORDER BY p.trend DESC NULLS LAST LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------- Apify eBay scraping ----------

def build_search_url(card: dict) -> str:
    """Build eBay search URL for Apify actor."""
    name = card.get("eng_name") or card.get("name", "")
    number = card.get("collector_number", "")
    name = re.sub(r"[^\w\s&'-]", "", name).strip()

    parts = ["Pokemon", name]
    if number:
        parts.append(str(number))

    query = quote_plus(" ".join(parts))
    return f"https://www.ebay.com/sch/i.html?_nkw={query}&_sacat=183454"


def run_apify_batch(
    token: str,
    search_urls: list[str],
    max_items_per_url: int = 5,
) -> list[dict]:
    """Run Apify eBay scraper on a batch of search URLs.

    Returns list of eBay items with image URLs.
    """
    # Start actor run
    resp = requests.post(
        f"{APIFY_API}/acts/{APIFY_ACTOR}/runs",
        params={"token": token},
        json={
            "startUrls": [{"url": u} for u in search_urls],
            "maxItems": max_items_per_url * len(search_urls),
        },
        timeout=30,
    )
    resp.raise_for_status()
    run_data = resp.json()["data"]
    run_id = run_data["id"]
    print(f"  Apify run started: {run_id}")

    # Poll until finished (max 5 min)
    for _ in range(60):
        time.sleep(5)
        status_resp = requests.get(
            f"{APIFY_API}/actor-runs/{run_id}",
            params={"token": token},
            timeout=15,
        )
        status = status_resp.json()["data"]["status"]
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            break

    if status != "SUCCEEDED":
        print(f"  Apify run {status}: {run_id}")
        return []

    # Fetch results
    dataset_id = status_resp.json()["data"]["defaultDatasetId"]
    items_resp = requests.get(
        f"{APIFY_API}/datasets/{dataset_id}/items",
        params={"token": token, "format": "json"},
        timeout=30,
    )
    items_resp.raise_for_status()
    return items_resp.json()


def download_image(url: str, save_path: Path) -> bool:
    """Download image. Returns True on success."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        if len(resp.content) < 5000:
            return False
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(resp.content)
        return True
    except Exception:
        return False


def _upscale_url(url: str) -> str:
    """Convert eBay thumbnail to full-size."""
    url = re.sub(r"/s-l\d+\.", "/s-l1600.", url)
    url = re.sub(r"\?.*$", "", url)
    return url


# ---------- Main ----------

def match_ebay_items_to_cards(
    items: list[dict],
    cards: list[dict],
) -> list[tuple[dict, dict]]:
    """Match Apify eBay results back to our card DB.

    Returns list of (ebay_item, card) pairs.
    Uses the search URL to trace which card each result came from.
    """
    # Build card lookup by search URL
    card_by_query: dict[str, dict] = {}
    for card in cards:
        url = build_search_url(card)
        card_by_query[url] = card

    pairs = []
    for item in items:
        # Apify includes the search URL that produced each result
        search_url = item.get("searchUrl", "")
        card = card_by_query.get(search_url)
        if not card:
            # Fallback: try matching by title keywords
            title = item.get("title", "").lower()
            for c in cards:
                name = (c.get("eng_name") or c.get("name", "")).lower()
                num = str(c.get("collector_number", ""))
                if name[:10] in title and num in title:
                    card = c
                    break
        if card:
            pairs.append((item, card))

    return pairs


def main():
    parser = argparse.ArgumentParser(description="Scrape eBay photos via Apify")
    parser.add_argument("--token", type=str, default=None, help="Apify API token")
    parser.add_argument("--cards", type=int, default=200, help="Number of cards")
    parser.add_argument("--per-card", type=int, default=3, help="Max photos per card")
    parser.add_argument("--batch-size", type=int, default=10,
                        help="Cards per Apify run (fewer = cheaper)")
    parser.add_argument("--lang", type=str, default="en", help="Card language")
    parser.add_argument("--set", type=str, default=None, help="Set ID filter")
    parser.add_argument("--resume", action="store_true", help="Skip already-scraped")
    args = parser.parse_args()

    token = args.token or os.environ.get("APIFY_TOKEN", "")
    if not token:
        print("Provide --token or set APIFY_TOKEN env var")
        print("Get yours at: https://console.apify.com/account/integrations")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Resume support
    scraped_ids: set[str] = set()
    if args.resume and PAIRS_FILE.exists():
        with open(PAIRS_FILE, "r") as f:
            for line in f:
                try:
                    scraped_ids.add(json.loads(line)["tcgdex_id"])
                except (json.JSONDecodeError, KeyError):
                    pass
        print(f"Resuming: skipping {len(scraped_ids)} already-scraped cards")

    print(f"Loading top {args.cards} cards (lang={args.lang}, set={args.set})...")
    cards = load_cards(DB_PATH, lang=args.lang, set_id=args.set, limit=args.cards)
    # Filter out already scraped
    cards = [c for c in cards if c["tcgdex_id"] not in scraped_ids]
    print(f"Scraping {len(cards)} cards in batches of {args.batch_size}")

    total_pairs = 0
    total_batches = (len(cards) + args.batch_size - 1) // args.batch_size

    with open(PAIRS_FILE, "a", encoding="utf-8") as f:
        for batch_idx in range(0, len(cards), args.batch_size):
            batch = cards[batch_idx:batch_idx + args.batch_size]
            batch_num = batch_idx // args.batch_size + 1

            print(f"\n--- Batch {batch_num}/{total_batches} "
                  f"({len(batch)} cards) ---")

            # Build search URLs for this batch
            search_urls = [build_search_url(c) for c in batch]
            for c, url in zip(batch, search_urls):
                name = (c.get("eng_name") or c["name"])[:40]
                print(f"  {name} -> {url.split('_nkw=')[1].split('&')[0]}")

            # Run Apify actor
            try:
                items = run_apify_batch(
                    token, search_urls,
                    max_items_per_url=args.per_card,
                )
            except Exception as e:
                print(f"  Apify error: {e}")
                continue

            print(f"  Got {len(items)} eBay items")
            if not items:
                continue

            # Match results to cards and download photos
            matched = match_ebay_items_to_cards(items, batch)
            print(f"  Matched {len(matched)} items to cards")

            # Group by card, limit per_card
            card_photo_count: dict[str, int] = {}

            for ebay_item, card in matched:
                tcgdex_id = card["tcgdex_id"]
                count = card_photo_count.get(tcgdex_id, 0)
                if count >= args.per_card:
                    continue

                # Get image URL from Apify result
                img_url = ebay_item.get("image", "")
                if not img_url:
                    # Try thumbnailUrl or gallery
                    img_url = ebay_item.get("thumbnailUrl", "")
                if not img_url:
                    continue

                img_url = _upscale_url(img_url)
                card_dir = OUTPUT_DIR / tcgdex_id.replace("/", "_")
                save_path = card_dir / f"ebay_{count:03d}.jpg"

                if download_image(img_url, save_path):
                    pair = {
                        "image_path": str(save_path),
                        "tcgdex_id": tcgdex_id,
                        "card_name": card.get("eng_name") or card.get("name", ""),
                        "clean_image_url": card.get("image_url", ""),
                        "source_url": ebay_item.get("url", ""),
                        "source": "ebay_apify",
                    }
                    f.write(json.dumps(pair, ensure_ascii=False) + "\n")
                    card_photo_count[tcgdex_id] = count + 1
                    total_pairs += 1

            batch_photos = sum(card_photo_count.values())
            print(f"  Downloaded {batch_photos} photos this batch")

            # Brief pause between batches
            if batch_idx + args.batch_size < len(cards):
                time.sleep(3)

    print(f"\n{'='*60}")
    print(f"Total: {total_pairs} photos downloaded")
    print(f"Pairs: {PAIRS_FILE}")
    print(f"Photos: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
