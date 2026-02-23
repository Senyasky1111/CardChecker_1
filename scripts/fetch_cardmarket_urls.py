"""
Scrape CardMarket expansion pages to collect direct product URLs.

Semi-automated: launches a VISIBLE browser. You solve the Cloudflare
challenge once (click the checkbox if asked), then the script takes over
and automatically crawls all expansion pages.

Strategy:
1. Open CardMarket in a visible browser (with persistent profile).
2. Wait for Cloudflare challenge to resolve (you may need to click once).
3. Load the Expansions listing to discover all expansion slugs.
4. For each expansion, paginate through the singles LIST view.
5. Extract (idProduct -> url_slug) pairs using DOM selectors + image URLs.
6. Save results incrementally to data/cardmarket/_url_slugs.json.

URL structure on CardMarket:
    Page:  /en/Pokemon/Products/Singles/{ExpansionSlug}/{CardSlug}
    Image: product-images.s3.cardmarket.com/51/{SetAbbr}/{idProduct}/{idProduct}.jpg

We use list view (?mode=list) instead of gallery because list view loads
all images eagerly (no lazy loading), making extraction more reliable.

Usage:
    python scripts/fetch_cardmarket_urls.py                # full run
    python scripts/fetch_cardmarket_urls.py --resume       # skip already-done expansions
    python scripts/fetch_cardmarket_urls.py --test 3       # only first 3 expansions
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page

DATA_DIR = Path("./data/cardmarket")
OUTPUT_FILE = DATA_DIR / "_url_slugs.json"
PROFILE_DIR = DATA_DIR / "_browser_profile"

CM_BASE = "https://www.cardmarket.com"
LOCALE = "en"
EXPANSIONS_URL = f"{CM_BASE}/{LOCALE}/Pokemon/Expansions"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _delay(lo: float = 2.0, hi: float = 5.0) -> None:
    time.sleep(random.uniform(lo, hi))


def _find_chrome() -> str | None:
    """Find the user's installed Chrome executable."""
    import os
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _extract_id_from_img(src: str) -> int | None:
    """Extract idProduct from image URL like:
    https://product-images.s3.cardmarket.com/51/BS/273741/273741.jpg
    """
    m = re.search(r"/(\d{5,8})/\d+\.\w+$", src)
    return int(m.group(1)) if m else None


def _wait_for_cloudflare(page: Page, timeout: int = 120) -> bool:
    """Wait for Cloudflare challenge to resolve.
    Returns True if page loaded, False if timed out.
    """
    for i in range(timeout):
        try:
            title = page.title()
        except Exception:
            time.sleep(1)
            continue
        if "Access denied" in title:
            # Hard block — need to wait and retry
            if i == 0:
                print("    Cloudflare ACCESS DENIED — waiting for manual resolution...")
            if i % 15 == 14:
                print(f"    Still blocked... ({i+1}s)")
            time.sleep(1)
            continue
        if "Just a moment" not in title and "Checking" not in title:
            return True
        if i == 5:
            print("    Cloudflare challenge detected -- please solve it in the browser window")
        if i % 15 == 14:
            print(f"    Still waiting... ({i+1}s)")
        time.sleep(1)
    return False


def _load_page(page: Page, url: str, retries: int = 3) -> bool:
    """Navigate to url and wait for Cloudflare to pass.

    Retries on Access Denied by refreshing after a delay.
    """
    for attempt in range(retries):
        try:
            page.goto(url, timeout=60000)
        except Exception as e:
            print(f"    Navigation warning: {e}")

        if _wait_for_cloudflare(page, timeout=30):
            return True

        # Check if we got Access Denied
        try:
            title = page.title()
        except Exception:
            title = ""

        if "Access denied" in title and attempt < retries - 1:
            wait_sec = 15 * (attempt + 1)
            print(f"    Retry {attempt + 2}/{retries} in {wait_sec}s...")
            time.sleep(wait_sec)
            # Go back to main page to reset CF state
            try:
                page.goto(f"{CM_BASE}/{LOCALE}/Pokemon", timeout=60000)
                _wait_for_cloudflare(page, timeout=60)
                _delay(3, 5)
            except Exception:
                pass
            continue

        if "Access denied" not in title:
            # Some other issue — try the longer timeout
            if _wait_for_cloudflare(page, timeout=90):
                return True

    return False


# ------------------------------------------------------------------
# Scraping
# ------------------------------------------------------------------

def scrape_expansion_slugs(page: Page) -> list[dict]:
    """Get all expansion slugs from the Expansions page."""
    print(f"\nLoading expansions page...")
    if not _load_page(page, EXPANSIONS_URL):
        print("ERROR: Could not load expansions page (Cloudflare timeout)")
        return []

    html = page.content()
    # Links: /en/Pokemon/Expansions/{slug}
    raw = re.findall(
        rf'href="/{LOCALE}/Pokemon/Expansions/([A-Za-z0-9][A-Za-z0-9\-]*)"',
        html
    )
    slugs = list(dict.fromkeys(raw))  # dedupe preserving order
    expansions = []
    for slug in slugs:
        singles_url = f"{CM_BASE}/{LOCALE}/Pokemon/Products/Singles/{slug}"
        expansions.append({"slug": slug, "url": singles_url})

    print(f"  Found {len(expansions)} expansion slugs")
    return expansions


def _extract_cards_from_page(page: Page, expansion_slug: str) -> list[dict]:
    """Extract card data from the current page using DOM selectors.

    Works with both list and gallery views. For each card entry on the page,
    finds the product link (href with slug) and the product image (src with
    idProduct encoded in the path).

    Returns list of {id_product, url_slug} dicts.
    """
    html = page.content()
    results: list[dict] = []
    seen_slugs: set[str] = set()

    # Strategy: find all <a> links pointing to a card product page, then
    # locate the nearest <img> with a product-images URL to get idProduct.
    #
    # In list view, the HTML structure is:
    #   <img src="...product-images.../51/SSP/794373/794373.jpg" ...>
    #   ... (within the same row) ...
    #   <a href="/en/Pokemon/Products/Singles/Surging-Sparks/Card-Name-SSP076">
    #
    # We extract all (href, img_src) pairs from the full HTML.

    # Step 1: collect all product image URLs → idProduct mapping
    img_pattern = re.findall(
        r'product-images\.s3\.cardmarket\.com/\d+/\w+/(\d+)/\d+\.\w+',
        html,
    )
    # Each idProduct appears in order on the page
    page_product_ids = []
    seen_ids_on_page: set[str] = set()
    for pid_str in img_pattern:
        if pid_str not in seen_ids_on_page:
            page_product_ids.append(pid_str)
            seen_ids_on_page.add(pid_str)

    # Step 2: collect all card slugs from links
    link_pattern = re.findall(
        rf'href="/{LOCALE}/Pokemon/Products/Singles/'
        rf'{re.escape(expansion_slug)}/([^"?]+)"',
        html,
    )
    page_slugs = []
    seen_link_slugs: set[str] = set()
    for slug in link_pattern:
        if slug not in seen_link_slugs:
            page_slugs.append(slug)
            seen_link_slugs.add(slug)

    # Step 3: pair them up (they appear in the same order on the page)
    paired = min(len(page_product_ids), len(page_slugs))
    for i in range(paired):
        pid = int(page_product_ids[i])
        slug = f"{expansion_slug}/{page_slugs[i]}"
        if slug not in seen_slugs:
            results.append({"id_product": pid, "url_slug": slug})
            seen_slugs.add(slug)

    # If we have unmatched slugs (e.g. lazy-loaded images), log it
    if len(page_slugs) > paired:
        unmatched = len(page_slugs) - paired
        print(f"    ({unmatched} cards without product images — lazy loading?)")

    return results


def scrape_expansion_cards(page: Page, expansion: dict) -> list[dict]:
    """Scrape all singles from one expansion (all pages).

    Uses list view (?mode=list) for reliable image loading.
    """
    base_url = expansion["url"]
    all_cards: list[dict] = []

    # Use list view — images load eagerly (no lazy loading issues)
    list_url = f"{base_url}?mode=list"
    if not _load_page(page, list_url):
        print("    Could not load page (Cloudflare)")
        return []

    _delay(1, 2)

    # Total pages from "Page X of Y"
    total_pages = 1
    html = page.content()
    m = re.search(r"Page\s+\d+\s+of\s+(\d+)", html)
    if m:
        total_pages = int(m.group(1))

    for page_num in range(1, total_pages + 1):
        if page_num > 1:
            url = f"{base_url}?mode=list&site={page_num}"
            # Longer delay between pages to avoid Cloudflare rate limiting
            _delay(3, 6)
            if not _load_page(page, url):
                print(f"    Page {page_num} failed, skipping rest")
                break
            _delay(1, 2)

        cards = _extract_cards_from_page(page, expansion["slug"])

        all_cards.extend(cards)

        if total_pages > 1:
            print(f"    Page {page_num}/{total_pages}: {len(cards)} cards")

    return all_cards


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape CardMarket direct product URLs"
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip expansions already scraped"
    )
    parser.add_argument(
        "--test", type=int, default=0,
        help="Only scrape first N expansions"
    )
    parser.add_argument(
        "--expansion", type=str, default="",
        help="Scrape only this expansion slug (e.g. Surging-Sparks)"
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing progress
    existing: dict[str, str] = {}
    scraped_expansions: set[str] = set()
    if args.resume and OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            existing = data.get("slugs", {})
            scraped_expansions = set(data.get("scraped_expansions", []))
        print(f"Resuming: {len(existing)} URLs, {len(scraped_expansions)} expansions done")

    # Launch using the user's installed Chrome (better Cloudflare compatibility)
    # Falls back to bundled Chromium if Chrome is not found.
    chrome_path = _find_chrome()
    profile_dir = str(PROFILE_DIR.resolve())

    with sync_playwright() as p:
        launch_kwargs: dict = {
            "headless": False,
            "viewport": {"width": 1400, "height": 900},
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if chrome_path:
            launch_kwargs["executable_path"] = chrome_path
            print(f"Using Chrome: {chrome_path}")

        ctx = p.chromium.launch_persistent_context(
            profile_dir,
            **launch_kwargs,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # Warm up: go to CardMarket main page first
        print("Opening CardMarket...")
        print(">>> A Chrome window should appear now.")
        print(">>> If Cloudflare asks 'Verify you are human' — click the checkbox!")
        print(">>> Waiting up to 3 minutes...")
        try:
            page.goto(f"{CM_BASE}/{LOCALE}/Pokemon", timeout=30000)
        except Exception:
            pass  # timeout during CF challenge is expected
        if not _wait_for_cloudflare(page, timeout=180):
            print("ERROR: Could not pass Cloudflare after 3 minutes.")
            print("  Make sure you clicked the Cloudflare checkbox in the Chrome window.")
            ctx.close()
            return

        print(f"  OK! Page: {page.title()}")
        _delay(2, 3)

        # Get expansion list
        if args.expansion:
            # Single expansion mode — skip loading the full list
            expansions = [{
                "slug": args.expansion,
                "url": f"{CM_BASE}/{LOCALE}/Pokemon/Products/Singles/{args.expansion}",
            }]
        else:
            expansions = scrape_expansion_slugs(page)
            if not expansions:
                ctx.close()
                return

        if args.test > 0:
            expansions = expansions[:args.test]

        # Scrape each expansion
        total_new = 0
        errors = 0
        for idx, exp in enumerate(expansions):
            if exp["slug"] in scraped_expansions:
                continue

            print(f"[{idx+1}/{len(expansions)}] {exp['slug']}")

            try:
                cards = scrape_expansion_cards(page, exp)
            except Exception as e:
                print(f"    ERROR: {e}")
                errors += 1
                if errors > 5:
                    print("Too many errors, stopping.")
                    break
                _delay(5, 10)
                continue

            for card in cards:
                pid = str(card["id_product"])
                existing[pid] = card["url_slug"]
                total_new += 1

            # Only mark as scraped if we found cards (empty sets should be retried)
            if cards:
                scraped_expansions.add(exp["slug"])

            # Save after each expansion
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "total_urls": len(existing),
                    "scraped_expansions": sorted(scraped_expansions),
                    "slugs": existing,
                }, f, ensure_ascii=False)

            print(f"    {len(cards)} cards | Total: {len(existing)}")

            # Polite delay
            _delay(3, 6)

        ctx.close()

    print(f"\nDone! {len(existing)} URLs in {OUTPUT_FILE}")
    print(f"  New: {total_new} | Expansions: {len(scraped_expansions)}")


if __name__ == "__main__":
    main()
