"""
Scrape Japanese Pokemon cards from the official pokemon-card.com database.

Uses a thread pool for fast HTTP fetching with single-threaded DB writes.

Usage:
    py -3.11 scripts/scrape_pokemon_card_jp.py              # scrape new cards
    py -3.11 scripts/scrape_pokemon_card_jp.py --resume      # continue from last ID
    py -3.11 scripts/scrape_pokemon_card_jp.py --start 43000 # start from specific ID
    py -3.11 scripts/scrape_pokemon_card_jp.py --download-images  # also download images
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

BASE_URL = "https://www.pokemon-card.com/card-search/details.php/card/{id}"
IMAGE_BASE = "https://www.pokemon-card.com"
PROGRESS_FILE = Path("data/scrape_jp_progress.json")
IMAGE_DIR = Path("data/cardmarket/images")

# Concurrency & rate limiting — conservative to avoid 403 bans
WORKERS = 3  # concurrent HTTP requests
BATCH_SIZE = 50  # IDs per batch
DELAY_EMPTY = 0.5  # seconds between batches with no cards (light load)
DELAY_WITH_CARDS = 5.0  # seconds between batches that found cards (heavy load)
REQUEST_TIMEOUT = 15
MAX_CARD_ID = 50100  # Upper bound: last known card ~50041, plus safety margin

# Regex for card number like "130 / 165" or "001/080"
_NUMBER_RE = re.compile(r"(\d{1,4})\s*/\s*(\d{1,4})")

# Rarity mapping from icon filename
_RARITY_MAP = {
    "ic_rare_c_c": "Common",
    "ic_rare_u_c": "Uncommon",
    "ic_rare_r_c": "Rare",
    "ic_rare_rr_c": "Double Rare",
    "ic_rare_sr_c": "Super Rare",
    "ic_rare_sar_c": "Special Art Rare",
    "ic_rare_ar_c": "Art Rare",
    "ic_rare_ur_c": "Ultra Rare",
    "ic_rare_hr_c": "Hyper Rare",
    "ic_rare_pr_c": "Promo",
    "ic_rare_tr_c": "Trainer Rare",
    "ic_rare_ace_c": "ACE SPEC Rare",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ja",
}


def _load_progress() -> dict:
    """Load scraping progress from file."""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_id": 0, "scraped_count": 0, "errors": []}


def _save_progress(progress: dict) -> None:
    """Save scraping progress to file."""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)


def _normalize_name(name: str) -> str:
    """Normalize card name for matching (preserve CJK characters)."""
    name = re.sub(r"\s*\[.*?\]", "", name)
    name = re.sub(r"\s*\(.*?\)", "", name)
    # Keep CJK, Latin, digits; remove punctuation
    name = re.sub(r"[^\w\u3000-\u9FFF\uF900-\uFAFF]", "", name)
    return name.lower().strip()


def fetch_card(card_id: int, session: requests.Session) -> dict | None:
    """
    Fetch and parse a single card page.

    Returns dict with card data, or None if page doesn't exist.
    Raises RuntimeError on 403 to trigger backoff in the caller.
    """
    url = BASE_URL.format(id=card_id)
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return None
        if resp.status_code == 403:
            raise RuntimeError(f"403 Forbidden at ID {card_id}")
        resp.raise_for_status()
        resp.encoding = "utf-8"
    except requests.RequestException:
        return None  # Skip on network errors, don't crash

    soup = BeautifulSoup(resp.text, "html.parser")

    # Check if it's a valid card page (has an h1 with card name)
    h1 = soup.find("h1")
    if not h1 or not h1.get_text(strip=True):
        return None

    card_name = h1.get_text(strip=True)

    # "カード検索" means "Card Search" — the site redirected to search page (card doesn't exist)
    if card_name == "カード検索":
        return None

    # Also check: valid cards have a card image
    if not soup.find("img", class_="fit"):
        return None

    # Image URL
    image_url = ""
    img_tag = soup.find("img", class_="fit")
    if img_tag and img_tag.get("src"):
        src = img_tag["src"]
        if src.startswith("/"):
            image_url = IMAGE_BASE + src
        else:
            image_url = src

    # Set code from regulation image (e.g., SV2a.gif)
    set_code = ""
    reg_img = soup.find("img", class_="img-regulation")
    if reg_img and reg_img.get("src"):
        m = re.search(r"/([^/]+)\.\w+$", reg_img["src"])
        if m:
            set_code = m.group(1)

    # Card number (e.g., "130 / 165")
    collector_number = None
    set_total = None
    page_text = soup.get_text()
    number_match = _NUMBER_RE.search(page_text)
    if number_match:
        collector_number = int(number_match.group(1))
        set_total = int(number_match.group(2))

    # Rarity from icon
    rarity = ""
    rarity_img = soup.find("img", width="24")
    if rarity_img and rarity_img.get("src"):
        for key, val in _RARITY_MAP.items():
            if key in rarity_img["src"]:
                rarity = val
                break

    # HP
    hp = None
    hp_span = soup.find("span", class_="hp-num")
    if hp_span:
        hp_text = hp_span.get_text(strip=True)
        m = re.search(r"\d+", hp_text)
        if m:
            hp = int(m.group())

    # Category
    category = "Pokemon"
    h2_tags = soup.find_all("h2")
    for h2 in h2_tags:
        text = h2.get_text(strip=True)
        if "トレーナーズ" in text or "サポート" in text or "グッズ" in text or "スタジアム" in text:
            category = "Trainer"
            break
        if "エネルギー" in text:
            category = "Energy"
            break
    if "ポケモンのどうぐ" in page_text:
        category = "Trainer"

    # Set name
    set_name = ""
    for a_tag in soup.find_all("a"):
        href = a_tag.get("href", "")
        if "/card-search/" in href and "expansion" in href:
            set_name = a_tag.get_text(strip=True)
            break
    if not set_name:
        set_name = set_code

    return {
        "site_id": card_id,
        "name": card_name,
        "name_normalized": _normalize_name(card_name),
        "set_code": set_code,
        "set_name": set_name,
        "collector_number": collector_number,
        "set_total": set_total,
        "rarity": rarity,
        "hp": hp,
        "category": category,
        "image_url": image_url,
    }


def download_image(card: dict, session: requests.Session) -> str:
    """Download card image and return local path."""
    if not card.get("image_url"):
        return ""

    set_code = card.get("set_code") or "unknown"
    site_id = card["site_id"]
    ext = card["image_url"].rsplit(".", 1)[-1] if "." in card["image_url"] else "jpg"
    local_dir = IMAGE_DIR / set_code
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / f"ja_jp-{site_id}.{ext}"

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
    """Insert or update a card in the database."""
    tcgdex_id = f"jp-{card['site_id']}"
    set_id = card.get("set_code") or "jp-unknown"

    # Ensure set exists
    existing = conn.execute("SELECT 1 FROM sets WHERE set_id = ?", (set_id,)).fetchone()
    if not existing:
        conn.execute(
            """INSERT INTO sets (set_id, name, abbreviation, card_count_official, language)
               VALUES (?, ?, ?, ?, 'ja')""",
            (set_id, card.get("set_name", set_id), set_id, card.get("set_total") or 0),
        )

    # Upsert card
    conn.execute(
        """INSERT OR REPLACE INTO cards
           (tcgdex_id, set_id, local_id, collector_number, set_total,
            name, name_normalized, eng_name, language, rarity, category,
            hp, image_url, image_local, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, '', 'ja', ?, ?, ?, ?, ?, datetime('now'))""",
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


_rate_limited = False  # Flag to signal 403 detected


def _fetch_batch(card_ids: list[int], download_images: bool) -> list[tuple[dict, str]]:
    """Fetch a batch of cards using a thread pool. Returns list of (card, image_local)."""
    global _rate_limited
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
                pass  # Skip failed fetches

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

    print(f"Starting JP scrape from ID {start_id} to {max_id}")
    print(f"  {total_ids} IDs to check in {total_batches} batches of {BATCH_SIZE}")
    print(f"  {WORKERS} workers, delay: {DELAY_EMPTY}s empty / {DELAY_WITH_CARDS}s with cards")

    t0 = time.time()

    global _rate_limited
    backoff_time = 60  # Initial backoff on 403

    for batch_idx in range(total_batches):
        batch_start = start_id + batch_idx * BATCH_SIZE
        batch_end = min(batch_start + BATCH_SIZE, max_id + 1)
        batch_ids = list(range(batch_start, batch_end))

        # Fetch batch concurrently
        _rate_limited = False
        results = _fetch_batch(batch_ids, download_images)

        # Handle 403 rate limiting
        if _rate_limited:
            print(f"  [RATE LIMITED] 403 detected at batch {batch_idx}. Backing off {backoff_time}s...")
            time.sleep(backoff_time)
            backoff_time = min(backoff_time * 2, 600)  # Max 10 minutes
            # Retry this batch
            _rate_limited = False
            results = _fetch_batch(batch_ids, download_images)
            if _rate_limited:
                print(f"  [STILL LIMITED] Waiting {backoff_time}s more...")
                time.sleep(backoff_time)
                continue  # Skip this batch, will be caught by resume
        else:
            backoff_time = 60  # Reset backoff on success

        # Save to DB (single-threaded)
        for card, image_local in results:
            save_card_to_db(conn, card, image_local)
            scraped += 1

        # Commit after each batch
        if results:
            conn.commit()
        progress["last_id"] = batch_end - 1
        progress["scraped_count"] = scraped
        _save_progress(progress)

        # Progress logging every 50 batches (1000 IDs)
        if (batch_idx + 1) % 50 == 0 or batch_idx == total_batches - 1:
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

        # Smart rate limiting: longer delay when server actually serves content
        delay = DELAY_WITH_CARDS if results else DELAY_EMPTY
        time.sleep(delay)

    # Final commit
    conn.commit()
    progress["last_id"] = max_id
    progress["scraped_count"] = scraped
    _save_progress(progress)

    elapsed = time.time() - t0
    print(f"\nScraping complete in {elapsed/60:.1f} minutes!")
    print(f"  Total scraped: {scraped}")

    row = conn.execute(
        "SELECT count(*) FROM cards WHERE language = 'ja'"
    ).fetchone()
    print(f"  JP cards in DB: {row[0]}")


def main():
    global WORKERS
    parser = argparse.ArgumentParser(description="Scrape JP Pokemon cards")
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
