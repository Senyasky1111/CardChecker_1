"""
Scrape CardMarket URLs by connecting to an EXISTING Chrome via CDP.

This avoids Cloudflare detection because it uses your real Chrome browser,
not a Playwright-launched one.

Steps:
1. Close ALL Chrome windows
2. Run this script — it will launch Chrome with remote debugging enabled
3. In the Chrome window that opens, navigate to cardmarket.com manually
4. Pass the Cloudflare check (click checkbox if needed)
5. Press Enter in this terminal when you see the CardMarket homepage
6. The script takes over and scrapes automatically

Usage:
    py -3.11 scripts/fetch_urls_cdp.py
    py -3.11 scripts/fetch_urls_cdp.py --resume
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, BrowserContext

DATA_DIR = Path("./data/cardmarket")
OUTPUT_FILE = DATA_DIR / "_url_slugs.json"

CM_BASE = "https://www.cardmarket.com"
LOCALE = "en"
EXPANSIONS_URL = f"{CM_BASE}/{LOCALE}/Pokemon/Expansions"
CDP_PORT = 9222


def _delay(lo: float = 2.0, hi: float = 5.0) -> None:
    time.sleep(random.uniform(lo, hi))


def _find_chrome() -> str:
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("Chrome not found")


def _extract_cards_from_page(page: Page, expansion_slug: str) -> list[dict]:
    """Extract card data from the current page."""
    html = page.content()
    results: list[dict] = []
    seen_slugs: set[str] = set()

    # Product image URLs → idProduct
    img_pattern = re.findall(
        r'product-images\.s3\.cardmarket\.com/\d+/\w+/(\d+)/\d+\.\w+',
        html,
    )
    page_product_ids = []
    seen_ids: set[str] = set()
    for pid_str in img_pattern:
        if pid_str not in seen_ids:
            page_product_ids.append(pid_str)
            seen_ids.add(pid_str)

    # Card slugs from links
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

    # Pair them
    paired = min(len(page_product_ids), len(page_slugs))
    for i in range(paired):
        pid = int(page_product_ids[i])
        slug = f"{expansion_slug}/{page_slugs[i]}"
        if slug not in seen_slugs:
            results.append({"id_product": pid, "url_slug": slug})
            seen_slugs.add(slug)

    return results


def _wait_for_page(page: Page, timeout_sec: int = 90) -> bool:
    """Wait for Cloudflare Waiting Room / challenge to resolve.
    Returns True if page loaded successfully."""
    for i in range(timeout_sec):
        try:
            title = page.title()
        except Exception:
            time.sleep(1)
            continue

        # Success — real page loaded
        if ("Waiting" not in title
                and "Access denied" not in title
                and "Just a moment" not in title
                and "Checking" not in title):
            return True

        if i == 5:
            print(f"    Waiting Room... (will wait up to {timeout_sec}s)")
        if i % 20 == 19:
            print(f"    Still in Waiting Room... ({i+1}s)")
        time.sleep(1)

    return False


def scrape_expansion(page: Page, slug: str) -> list[dict]:
    """Scrape all singles from one expansion."""
    base_url = f"{CM_BASE}/{LOCALE}/Pokemon/Products/Singles/{slug}"
    all_cards: list[dict] = []

    list_url = f"{base_url}?mode=list"
    page.goto(list_url, timeout=60000, wait_until="domcontentloaded")
    _delay(1, 2)

    # Wait for Cloudflare Waiting Room to resolve
    if not _wait_for_page(page, timeout_sec=90):
        print(f"    BLOCKED by Cloudflare on {slug}")
        return []

    _delay(1, 2)

    # Total pages
    html = page.content()
    total_pages = 1
    m = re.search(r"Page\s+\d+\s+of\s+(\d+)", html)
    if m:
        total_pages = int(m.group(1))

    for page_num in range(1, total_pages + 1):
        if page_num > 1:
            url = f"{base_url}?mode=list&site={page_num}"
            _delay(5, 10)
            page.goto(url, timeout=60000, wait_until="domcontentloaded")

            if not _wait_for_page(page, timeout_sec=60):
                print(f"    BLOCKED on page {page_num}")
                break
            _delay(1, 2)

        cards = _extract_cards_from_page(page, slug)
        all_cards.extend(cards)

        if total_pages > 1:
            print(f"    Page {page_num}/{total_pages}: {len(cards)} cards")

    return all_cards


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing
    existing: dict[str, str] = {}
    scraped_expansions: set[str] = set()
    if args.resume and OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            existing = data.get("slugs", {})
            scraped_expansions = set(data.get("scraped_expansions", []))
        print(f"Resuming: {len(existing)} URLs, {len(scraped_expansions)} expansions done")

    # Launch Chrome with remote debugging
    chrome_path = _find_chrome()
    user_data = str((DATA_DIR / "_cdp_profile").resolve())
    os.makedirs(user_data, exist_ok=True)

    print(f"\nLaunching Chrome with remote debugging on port {CDP_PORT}...")
    print("IMPORTANT: Close ALL other Chrome windows first!\n")

    chrome_proc = subprocess.Popen([
        chrome_path,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={user_data}",
        f"{CM_BASE}/{LOCALE}/Pokemon",
    ])

    print("=" * 60)
    print("Chrome should have opened with CardMarket.")
    print("If Cloudflare challenge appears — solve it in the browser!")
    print("Waiting up to 3 minutes for page to load...")
    print("=" * 60)

    # Wait for Chrome to load and pass Cloudflare
    for i in range(180):
        time.sleep(1)
        try:
            with sync_playwright() as p_check:
                br = p_check.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
                ctx_check = br.contexts[0]
                pg = ctx_check.pages[0] if ctx_check.pages else None
                if pg:
                    title = pg.title()
                    url = pg.url
                    br.close()
                    if "cardmarket.com" in url and "Waiting" not in title and "Just a moment" not in title and "Access denied" not in title:
                        print(f"  CardMarket loaded! ({title})")
                        break
                else:
                    br.close()
        except Exception:
            pass
        if i == 10:
            print("  Still waiting for Cloudflare...")
        if i % 30 == 29:
            print(f"  Waiting... ({i+1}s)")
    else:
        print("ERROR: Could not connect to CardMarket after 3 minutes.")
        chrome_proc.terminate()
        return

    # Connect via CDP
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        print(f"\nConnected! Page: {page.title()}")
        print(f"URL: {page.url}\n")

        # Get expansion list from the Expansions page
        print("Loading expansions page...")
        page.goto(EXPANSIONS_URL, timeout=60000, wait_until="domcontentloaded")
        if not _wait_for_page(page, timeout_sec=120):
            print("ERROR: Cloudflare blocked the Expansions page.")
            print("Try navigating there manually in the Chrome window, then re-run.")
            browser.close()
            chrome_proc.terminate()
            return
        _delay(1, 2)

        html = page.content()
        raw = re.findall(
            rf'href="/{LOCALE}/Pokemon/Expansions/([A-Za-z0-9][A-Za-z0-9\-]*)"',
            html
        )
        slugs = list(dict.fromkeys(raw))
        print(f"  Found {len(slugs)} expansion slugs")

        if not slugs:
            print("ERROR: No expansions found. Page might not have loaded correctly.")
            browser.close()
            chrome_proc.terminate()
            return

        # Scrape each expansion
        total_new = 0
        errors = 0
        blocked = 0

        for idx, exp_slug in enumerate(slugs):
            if exp_slug in scraped_expansions:
                continue

            print(f"[{idx+1}/{len(slugs)}] {exp_slug}")

            try:
                cards = scrape_expansion(page, exp_slug)
            except Exception as e:
                print(f"    ERROR: {e}")
                errors += 1
                if errors > 5:
                    print("Too many errors, stopping.")
                    break
                _delay(5, 10)
                continue

            if not cards:
                blocked += 1
                if blocked > 5:
                    print("Too many Cloudflare blocks, stopping. Run with --resume to continue.")
                    break
                # Long pause before retrying
                wait = 30 + blocked * 15
                print(f"    Pausing {wait}s before next attempt...")
                time.sleep(wait)
                continue
            else:
                blocked = 0  # reset on success

            for card in cards:
                pid = str(card["id_product"])
                existing[pid] = card["url_slug"]
                total_new += 1

            scraped_expansions.add(exp_slug)

            # Save after each expansion
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "total_urls": len(existing),
                    "scraped_expansions": sorted(scraped_expansions),
                    "slugs": existing,
                }, f, ensure_ascii=False)

            print(f"    {len(cards)} cards | Total: {len(existing)}")
            # Longer delays to avoid Cloudflare rate limiting
            _delay(6, 12)

        browser.close()
        # Don't kill Chrome — let user close it

    print(f"\nDone! {len(existing)} URLs in {OUTPUT_FILE}")
    print(f"  New: {total_new} | Expansions scraped: {len(scraped_expansions)}")


if __name__ == "__main__":
    main()
