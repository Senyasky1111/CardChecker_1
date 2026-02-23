from __future__ import annotations

"""
Download card images from TCGdex API in multiple languages, organized by set.

Languages: EN, JA, ZH-TW, ZH-CN  (configurable via --langs)
Structure: data/cardmarket/images/{set_id}/{lang}_{tcgdex_card_id}.jpg

TCGdex (https://tcgdex.dev) is free, fast, and provides HD card images.
No API key required, no Cloudflare.

Usage:
    python scripts/download_images_pokemontcg.py
    python scripts/download_images_pokemontcg.py --workers 15
    python scripts/download_images_pokemontcg.py --langs en ja
"""

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from tqdm import tqdm

DATA_DIR = Path("./data/cardmarket")
IMAGES_DIR = DATA_DIR / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

TCGDEX_API = "https://api.tcgdex.net/v2"

DEFAULT_LANGS = ["en", "ja", "zh-tw", "zh-cn"]


# ------------------------------------------------------------------
# TCGdex data fetching
# ------------------------------------------------------------------

def fetch_tcgdex_cards(lang: str) -> list[dict]:
    """Fetch all cards from TCGdex API for a given language.

    Returns list of cards with 'image' URLs.
    Uses a per-language cache file.
    """
    cache_file = DATA_DIR / f"_tcgdex_cache_{lang}.json"

    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            cards = json.load(f)
        print(f"  [{lang}] Loaded {len(cards)} cards from cache.")
        return cards

    print(f"  [{lang}] Fetching card list from TCGdex API...")
    resp = requests.get(f"{TCGDEX_API}/{lang}/cards", timeout=30)
    resp.raise_for_status()
    cards = resp.json()

    # Keep only cards that have images
    cards_with_img = [c for c in cards if c.get("image")]
    print(f"  [{lang}] {len(cards_with_img)} cards with images (of {len(cards)} total).")

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(cards_with_img, f, ensure_ascii=False)

    return cards_with_img


def fetch_tcgdex_sets(lang: str) -> dict[str, str]:
    """Fetch set ID → set name mapping for a language."""
    resp = requests.get(f"{TCGDEX_API}/{lang}/sets", timeout=15)
    resp.raise_for_status()
    sets_data = resp.json()
    return {s["id"]: s.get("name", s["id"]) for s in sets_data}


# ------------------------------------------------------------------
# Match TCGdex cards to CardMarket products
# ------------------------------------------------------------------

_CM_BRACKET_RE = re.compile(r"\s*\[.*?\]\s*")


def normalize_name(name: str) -> str:
    """Normalize a card name for matching."""
    name = _CM_BRACKET_RE.sub("", name)
    name = re.sub(r"\s*\(\d+/\d+\)", "", name)
    name = re.sub(r"\s*\(.*?\)", "", name)
    name = name.strip().lower()
    name = re.sub(r"[''`]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name


def match_tcgdex_to_cardmarket(
    tcgdex_cards: list[dict],
    cm_cards: list[dict],
) -> dict[str, int]:
    """Match TCGdex card IDs to CardMarket product IDs by name.

    Returns: {tcgdex_id: cm_id_product}
    """
    cm_by_name: dict[str, list[dict]] = {}
    for card in cm_cards:
        key = normalize_name(card["name"])
        cm_by_name.setdefault(key, []).append(card)

    matched: dict[str, int] = {}
    for tc in tcgdex_cards:
        tc_name = normalize_name(tc.get("name", ""))
        if tc_name in cm_by_name:
            matched[tc["id"]] = cm_by_name[tc_name][0]["id_product"]

    return matched


# ------------------------------------------------------------------
# Image download
# ------------------------------------------------------------------

def _extract_set_id(tcgdex_card_id: str) -> str:
    """Extract set ID from a TCGdex card ID like 'sv08-123' → 'sv08'."""
    parts = tcgdex_card_id.rsplit("-", 1)
    return parts[0] if len(parts) == 2 else "unknown"


def plan_downloads(
    cards_by_lang: dict[str, list[dict]],
    match_map: dict[str, int],
) -> list[tuple[str, str, str, Path]]:
    """Plan all downloads across languages.

    Returns list of (lang, tcgdex_id, url, local_path) tuples.
    """
    downloads: list[tuple[str, str, str, Path]] = []

    for lang, cards in cards_by_lang.items():
        for card in cards:
            tcgdex_id = card["id"]
            image_base = card.get("image", "")
            if not image_base:
                continue

            set_id = _extract_set_id(tcgdex_id)
            safe_id = tcgdex_id.replace("/", "_")

            # Directory per set
            set_dir = IMAGES_DIR / set_id
            set_dir.mkdir(parents=True, exist_ok=True)

            # Filename: {lang}_{tcgdex_id}.jpg
            filename = f"{lang}_{safe_id}.jpg"
            local_path = set_dir / filename

            if local_path.exists() and local_path.stat().st_size > 0:
                continue

            url = image_base + "/high.png"
            downloads.append((lang, tcgdex_id, url, local_path))

    return downloads


def download_images(
    downloads: list[tuple[str, str, str, Path]],
    max_workers: int = 10,
) -> tuple[int, int]:
    """Download images in parallel with progress bar.

    Returns (success_count, fail_count).
    """
    if not downloads:
        print("All images already downloaded!")
        return (0, 0)

    print(f"\nDownloading {len(downloads)} images ({max_workers} workers)...")
    session = requests.Session()
    success = 0
    fail = 0

    def _download(item: tuple[str, str, str, Path]) -> bool:
        _, _, url, path = item
        for attempt in range(3):
            try:
                r = session.get(url, timeout=30)
                if r.status_code == 200:
                    path.write_bytes(r.content)
                    return True
                elif r.status_code == 404:
                    return False
            except Exception:
                time.sleep(1 * (attempt + 1))
        return False

    pbar = tqdm(total=len(downloads), desc="Downloading", unit="img")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_download, item): item for item in downloads}
        for future in as_completed(futures):
            if future.result():
                success += 1
            else:
                fail += 1
            pbar.set_postfix(ok=success, fail=fail)
            pbar.update(1)

    pbar.close()
    return (success, fail)


def migrate_old_images(
    match_map: dict[str, int],
    cards_en: list[dict],
) -> int:
    """Move existing flat images from old structure into set-based subdirectories.

    Old format: images/{product_id}.jpg or images/tcg_{id}.jpg
    New format: images/{set_id}/en_{tcgdex_id}.jpg

    Returns count of migrated images.
    """
    migrated = 0

    # Build reverse map: product_id → tcgdex_id
    cm_to_tcg: dict[int, str] = {}
    for tcg_id, cm_id in match_map.items():
        cm_to_tcg[cm_id] = tcg_id

    # Check for old-style files in the flat images directory
    for old_file in IMAGES_DIR.glob("*.jpg"):
        if old_file.parent != IMAGES_DIR:
            continue  # Already in a subdirectory

        stem = old_file.stem
        tcgdex_id = None

        # Old format 1: {product_id}.jpg
        try:
            pid = int(stem)
            tcgdex_id = cm_to_tcg.get(pid)
        except ValueError:
            pass

        # Old format 2: tcg_{id}.jpg
        if tcgdex_id is None and stem.startswith("tcg_"):
            tcgdex_id = stem[4:].replace("_", "-")

        if tcgdex_id is None:
            continue

        set_id = _extract_set_id(tcgdex_id)
        safe_id = tcgdex_id.replace("/", "_")
        new_dir = IMAGES_DIR / set_id
        new_dir.mkdir(parents=True, exist_ok=True)
        new_path = new_dir / f"en_{safe_id}.jpg"

        if not new_path.exists():
            old_file.rename(new_path)
            migrated += 1
        else:
            old_file.unlink()  # Duplicate, remove old copy

    return migrated


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Download card images from TCGdex")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument(
        "--langs", nargs="+", default=DEFAULT_LANGS,
        help=f"Languages to download (default: {' '.join(DEFAULT_LANGS)})"
    )
    args = parser.parse_args()

    # Load CardMarket card list (for matching)
    cm_file = DATA_DIR / "cards_with_prices.json"
    cm_cards: list[dict] = []
    if cm_file.exists():
        with open(cm_file, "r", encoding="utf-8") as f:
            cm_data = json.load(f)
        cm_cards = cm_data.get("cards", [])
        print(f"Loaded {len(cm_cards)} CardMarket cards for price matching.")
    else:
        print("WARNING: cards_with_prices.json not found.")
        print("  Run first: python scripts/download_cardmarket_csvs.py")

    # Fetch TCGdex data for each language
    print(f"\nFetching TCGdex cards for languages: {args.langs}")
    cards_by_lang: dict[str, list[dict]] = {}
    total_cards = 0
    for lang in args.langs:
        cards = fetch_tcgdex_cards(lang)
        cards_by_lang[lang] = cards
        total_cards += len(cards)

    print(f"\nTotal cards across all languages: {total_cards}")

    # Match EN cards to CardMarket (for reference — matching is name-based)
    match_map: dict[str, int] = {}
    if cm_cards and "en" in cards_by_lang:
        match_map = match_tcgdex_to_cardmarket(cards_by_lang["en"], cm_cards)
        print(f"Matched {len(match_map)} EN cards to CardMarket IDs.")

        # Save match map for build_embedding_index.py
        match_file = DATA_DIR / "_tcgdex_match_map.json"
        with open(match_file, "w", encoding="utf-8") as f:
            json.dump(match_map, f, indent=2)
        print(f"Saved match map to {match_file}")

    # Migrate old flat images to new structure
    if "en" in cards_by_lang:
        migrated = migrate_old_images(match_map, cards_by_lang["en"])
        if migrated > 0:
            print(f"Migrated {migrated} old images to set-based directories.")

    # Plan and execute downloads
    downloads = plan_downloads(cards_by_lang, match_map)

    # Show per-language breakdown
    lang_counts: dict[str, int] = {}
    for lang, _, _, _ in downloads:
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
    for lang, count in sorted(lang_counts.items()):
        print(f"  [{lang}] {count} images to download")

    ok, fail = download_images(downloads, max_workers=args.workers)

    # Summary
    total_images = sum(1 for _ in IMAGES_DIR.rglob("*.jpg"))
    total_sets = sum(1 for d in IMAGES_DIR.iterdir() if d.is_dir())
    print(f"\nDone!")
    print(f"  Downloaded this run: {ok} ok, {fail} failed")
    print(f"  Total images on disk: {total_images}")
    print(f"  Total sets (directories): {total_sets}")
    print(f"  CardMarket-matched (EN): {len(match_map)}")
    print(f"\nNext step: python scripts/build_embedding_index.py")


if __name__ == "__main__":
    main()
