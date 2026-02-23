"""
Scrape Traditional Chinese (Taiwan) Pokemon cards from asia.pokemon-card.com/tw.

Uses a thread pool for fast HTTP fetching with single-threaded DB writes.

Usage:
    py -3.11 scripts/scrape_pokemon_card_tw.py              # scrape new cards
    py -3.11 scripts/scrape_pokemon_card_tw.py --resume      # continue from last ID
    py -3.11 scripts/scrape_pokemon_card_tw.py --start 1000  # start from specific ID
    py -3.11 scripts/scrape_pokemon_card_tw.py --download-images  # also download images
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import ensure_schema

BASE_URL = "https://asia.pokemon-card.com/tw/card-search/detail/{id}/"
PROGRESS_FILE = Path("data/scrape_tw_progress.json")
IMAGE_DIR = Path("data/cardmarket/images")

# Concurrency & rate limiting — conservative to avoid 403 bans
WORKERS = 3
BATCH_SIZE = 50
DELAY_EMPTY = 0.5       # seconds between batches with no cards
DELAY_WITH_CARDS = 3.0   # seconds between batches that found cards
REQUEST_TIMEOUT = 15
MAX_CARD_ID = 18500  # Upper bound: last known card ~18355, plus safety margin

_rate_limited = False  # Flag to signal 403 detected

# Regex for card number like "001/080"
_NUMBER_RE = re.compile(r"(\d{1,4})\s*/\s*(\d{1,4})")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "zh-TW",
}


def _load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_id": 0, "scraped_count": 0, "errors": []}


def _save_progress(progress: dict) -> None:
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)


def _normalize_name(name: str) -> str:
    """Normalize card name for matching (preserve CJK characters)."""
    name = re.sub(r"\s*\[.*?\]", "", name)
    name = re.sub(r"\s*\(.*?\)", "", name)
    name = re.sub(r"[^\w\u3000-\u9FFF\uF900-\uFAFF]", "", name)
    return name.lower().strip()


def fetch_card(card_id: int, session: requests.Session) -> dict | None:
    """
    Fetch and parse a single TW card page.

    Returns dict with card data, or None if page doesn't exist.
    """
    url = BASE_URL.format(id=card_id)
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.encoding = "utf-8"
        if resp.status_code == 404:
            return None
        if resp.status_code == 403:
            raise RuntimeError(f"403 Forbidden at ID {card_id}")
        resp.raise_for_status()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Check if it's a valid card detail page
    h1 = soup.find("h1", class_="pageHeader")
    if not h1:
        return None

    # Card name: text content of h1, excluding the evolveMarker span
    evolve_span = h1.find("span", class_="evolveMarker")
    if evolve_span:
        evolve_span.extract()
    card_name = h1.get_text(strip=True)

    if not card_name:
        return None

    # "卡牌搜尋結果" means "Card Search Results" — redirected, card doesn't exist
    if card_name in ("卡牌搜尋結果", "卡牌搜尋"):
        return None

    # Valid cards must have a card image
    if not soup.select_one("section.imageColumn img"):
        return None

    # Image URL
    image_url = ""
    img_section = soup.find("section", class_="imageColumn")
    if img_section:
        img_tag = img_section.find("img")
        if img_tag and img_tag.get("src"):
            image_url = img_tag["src"]

    # Collector number from span.collectorNumber (e.g., "001/080")
    collector_number = None
    set_total = None
    cn_span = soup.find("span", class_="collectorNumber")
    if cn_span:
        cn_text = cn_span.get_text(strip=True)
        m = _NUMBER_RE.search(cn_text)
        if m:
            collector_number = int(m.group(1))
            set_total = int(m.group(2))

    # Set code from expansion link (e.g., href="...?expansionCodes=M3")
    set_code = ""
    set_name = ""
    exp_section = soup.find("section", class_="expansionLinkColumn")
    if exp_section:
        a_tag = exp_section.find("a")
        if a_tag:
            set_name = a_tag.get_text(strip=True)
            href = a_tag.get("href", "")
            m = re.search(r"expansionCodes=([^&]+)", href)
            if m:
                set_code = m.group(1)

    # HP
    hp = None
    main_info = soup.find("p", class_="mainInfomation")
    if main_info:
        hp_span = main_info.find("span", class_="number")
        if hp_span:
            hp_text = hp_span.get_text(strip=True)
            if hp_text.isdigit():
                hp = int(hp_text)

    # Category
    category = "Pokemon"
    skill_info = soup.find("div", class_="skillInformation")
    if skill_info:
        h3 = skill_info.find("h3")
        if h3:
            h3_text = h3.get_text(strip=True)
            if "支援者" in h3_text or "物品" in h3_text or "競技場" in h3_text:
                category = "Trainer"
    if not skill_info and hp is None:
        page_text = soup.get_text()
        if "能量" in page_text:
            category = "Energy"
        else:
            category = "Trainer"

    return {
        "site_id": card_id,
        "name": card_name,
        "name_normalized": _normalize_name(card_name),
        "set_code": set_code,
        "set_name": set_name,
        "collector_number": collector_number,
        "set_total": set_total,
        "rarity": "",
        "hp": hp,
        "category": category,
        "image_url": image_url,
    }


def download_image(card: dict, session: requests.Session) -> str:
    """Download card image and return local path."""
    if not card.get("image_url"):
        return ""

    set_code = card.get("set_code") or "tw-unknown"
    site_id = card["site_id"]
    ext = card["image_url"].rsplit(".", 1)[-1] if "." in card["image_url"] else "png"
    local_dir = IMAGE_DIR / set_code
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / f"zh-tw_tw-{site_id}.{ext}"

    if local_path.exists():
        return str(local_path)

    try:
        resp = session.get(card["image_url"], timeout=30)
        resp.raise_for_status()
        local_path.write_bytes(resp.content)
        return str(local_path)
    except requests.RequestException:
        return ""


def save_card_to_db(conn, card: dict, image_local: str = "") -> None:
    """Insert or update a TW card in the database."""
    tcgdex_id = f"tw-{card['site_id']}"
    set_id = f"tw-{card.get('set_code') or 'unknown'}"

    # Ensure set exists
    existing = conn.execute("SELECT 1 FROM sets WHERE set_id = ?", (set_id,)).fetchone()
    if not existing:
        conn.execute(
            """INSERT INTO sets (set_id, name, abbreviation, card_count_official, language)
               VALUES (?, ?, ?, ?, 'zh-tw')""",
            (set_id, card.get("set_name", set_id), card.get("set_code", ""), card.get("set_total") or 0),
        )

    # Upsert card
    conn.execute(
        """INSERT OR REPLACE INTO cards
           (tcgdex_id, set_id, local_id, collector_number, set_total,
            name, name_normalized, eng_name, language, rarity, category,
            hp, image_url, image_local, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, '', 'zh-tw', ?, ?, ?, ?, ?, datetime('now'))""",
        (
            tcgdex_id,
            set_id,
            str(card.get("collector_number") or card["site_id"]),
            card.get("collector_number"),
            card.get("set_total"),
            card["name"],
            card["name_normalized"],
            card.get("rarity", ""),
            card.get("category", ""),
            card.get("hp"),
            card.get("image_url", ""),
            image_local,
        ),
    )


def _fetch_batch(card_ids: list[int], download_images: bool) -> list[tuple[dict, str]]:
    """Fetch a batch of cards using a thread pool."""
    session = requests.Session()
    session.headers.update(HEADERS)

    results = []

    def _fetch_one(cid: int) -> tuple[dict, str] | None:
        global _rate_limited
        try:
            card = fetch_card(cid, session)
        except RuntimeError:
            _rate_limited = True
            return None
        if card is None:
            return None
        img = ""
        if download_images:
            img = download_image(card, session)
        return (card, img)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_fetch_one, cid): cid for cid in card_ids}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    results.append(result)
            except Exception:
                pass

    return results


def scrape(
    start_id: int = 1,
    max_id: int = MAX_CARD_ID,
    download_images: bool = False,
    resume: bool = False,
) -> None:
    """Main scraping loop with concurrent HTTP fetching."""
    progress = _load_progress()
    if resume and progress["last_id"] > 0:
        start_id = progress["last_id"] + 1
        print(f"Resuming from ID {start_id} (previously scraped: {progress['scraped_count']})")

    conn = ensure_schema()
    scraped = progress.get("scraped_count", 0)
    total_ids = max_id - start_id + 1
    total_batches = (total_ids + BATCH_SIZE - 1) // BATCH_SIZE

    print(f"Starting TW scrape from ID {start_id} to {max_id}")
    print(f"  {total_ids} IDs to check in {total_batches} batches of {BATCH_SIZE}")
    print(f"  {WORKERS} concurrent workers, {DELAY_EMPTY}s/{DELAY_WITH_CARDS}s delay (empty/cards)")

    t0 = time.time()
    backoff_time = 60  # Initial backoff on 403

    for batch_idx in range(total_batches):
        global _rate_limited
        batch_start = start_id + batch_idx * BATCH_SIZE
        batch_end = min(batch_start + BATCH_SIZE, max_id + 1)
        batch_ids = list(range(batch_start, batch_end))

        _rate_limited = False
        results = _fetch_batch(batch_ids, download_images)

        # Handle 403 rate limiting
        if _rate_limited:
            print(f"  [RATE LIMITED] 403 detected. Backing off {backoff_time}s...")
            time.sleep(backoff_time)
            backoff_time = min(backoff_time * 2, 600)
            # Retry the same batch
            _rate_limited = False
            results = _fetch_batch(batch_ids, download_images)
            if _rate_limited:
                print(f"  [RATE LIMITED] Still blocked. Waiting {backoff_time}s...")
                time.sleep(backoff_time)
                backoff_time = min(backoff_time * 2, 600)
        else:
            backoff_time = 60  # Reset on success

        for card, image_local in results:
            save_card_to_db(conn, card, image_local)
            scraped += 1

        # Always save progress (even if no cards found in batch)
        progress["last_id"] = batch_end - 1
        progress["scraped_count"] = scraped
        if results:
            conn.commit()
        _save_progress(progress)

        if (batch_idx + 1) % 20 == 0 or batch_idx == total_batches - 1:
            elapsed = time.time() - t0
            ids_done = batch_end - start_id
            rate = ids_done / elapsed if elapsed > 0 else 0
            eta_s = (total_ids - ids_done) / rate if rate > 0 else 0
            eta_m = eta_s / 60
            print(
                f"  [PROGRESS] ID {batch_end-1}/{max_id} "
                f"({ids_done}/{total_ids} IDs, {scraped} cards) "
                f"— {rate:.0f} IDs/s, ETA {eta_m:.0f}min"
            )

        # Smart delay: shorter for empty batches, longer when cards found
        delay = DELAY_WITH_CARDS if results else DELAY_EMPTY
        time.sleep(delay)

    conn.commit()
    progress["last_id"] = max_id
    progress["scraped_count"] = scraped
    _save_progress(progress)

    elapsed = time.time() - t0
    print(f"\nScraping complete in {elapsed/60:.1f} minutes!")
    print(f"  Total scraped: {scraped}")

    row = conn.execute("SELECT count(*) FROM cards WHERE language = 'zh-tw'").fetchone()
    print(f"  TW cards in DB: {row[0]}")


def main():
    global WORKERS
    parser = argparse.ArgumentParser(description="Scrape TW Pokemon cards")
    parser.add_argument("--start", type=int, default=1, help="Start card ID")
    parser.add_argument("--max-id", type=int, default=MAX_CARD_ID, help="Max card ID to check")
    parser.add_argument("--resume", action="store_true", help="Resume from last progress")
    parser.add_argument("--download-images", action="store_true", help="Download card images")
    parser.add_argument("--workers", type=int, default=WORKERS, help="Concurrent HTTP workers")
    args = parser.parse_args()

    WORKERS = args.workers

    scrape(
        start_id=args.start,
        max_id=args.max_id,
        download_images=args.download_images,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()
