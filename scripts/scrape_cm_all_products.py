"""
Scrape ALL CardMarket product IDs by connecting to an EXISTING Chrome via CDP.

This collects idProduct for every card across every expansion (EN, JP, TW, etc.)
so we can build a complete mapping for our database.

How it works:
1. Launches Chrome with remote debugging
2. You manually pass Cloudflare challenge in the browser
3. Script scrapes the Expansions page to discover ALL expansion slugs
4. For each expansion, opens the Singles page and extracts:
   - idProduct (from product image URLs)
   - Card name (from link text)
   - URL slug (from link href)
5. Saves to data/cardmarket/_cm_products_all.json (resumable)

Usage:
    python scripts/scrape_cm_all_products.py           # Fresh start
    python scripts/scrape_cm_all_products.py --resume   # Continue from last save
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page

DATA_DIR = Path("./data/cardmarket")
OUTPUT_FILE = DATA_DIR / "_cm_products_all.json"

CM_BASE = "https://www.cardmarket.com"
LOCALE = "en"
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


def _wait_for_page(page: Page, timeout_sec: int = 90) -> bool:
    """Wait for Cloudflare challenge to resolve. Returns True if page loaded."""
    for i in range(timeout_sec):
        try:
            title = page.title()
        except Exception:
            time.sleep(1)
            continue

        if ("Waiting" not in title
                and "Access denied" not in title
                and "Just a moment" not in title
                and "Checking" not in title):
            return True

        if i == 5:
            print(f"    Waiting for Cloudflare... (up to {timeout_sec}s)")
        if i % 20 == 19:
            print(f"    Still waiting... ({i+1}s)")
        time.sleep(1)
    return False


def _extract_products_from_page(page: Page, expansion_slug: str) -> list[dict]:
    """Extract product data from the current expansion singles page."""
    html = page.content()
    results: list[dict] = []

    # Extract idProduct from product image URLs
    # Pattern: product-images.s3.cardmarket.com/{group}/{hash}/{idProduct}/{imageId}.{ext}
    img_ids = re.findall(
        r'product-images\.s3\.cardmarket\.com/\d+/\w+/(\d+)/\d+\.\w+',
        html,
    )
    page_product_ids = []
    seen_ids: set[str] = set()
    for pid_str in img_ids:
        if pid_str not in seen_ids:
            page_product_ids.append(pid_str)
            seen_ids.add(pid_str)

    # Extract card names + slugs from links
    # Pattern: href="/en/Pokemon/Products/Singles/{expansion}/{card-slug}"
    link_pattern = re.findall(
        rf'href="/{LOCALE}/Pokemon/Products/Singles/'
        rf'{re.escape(expansion_slug)}/([^"?]+)"[^>]*>([^<]*)<',
        html,
    )
    page_cards = []
    seen_slugs: set[str] = set()
    for slug, name in link_pattern:
        if slug not in seen_slugs:
            page_cards.append({"slug": slug, "name": name.strip()})
            seen_slugs.add(slug)

    # If we got more links than IDs (some links are duplicates for img/text),
    # re-extract with a simpler approach
    if not page_cards:
        raw_slugs = re.findall(
            rf'href="/{LOCALE}/Pokemon/Products/Singles/'
            rf'{re.escape(expansion_slug)}/([^"?]+)"',
            html,
        )
        seen_slugs = set()
        for slug in raw_slugs:
            if slug not in seen_slugs:
                page_cards.append({"slug": slug, "name": ""})
                seen_slugs.add(slug)

    # Also try to extract names from the card elements
    if page_cards and not page_cards[0]["name"]:
        try:
            names_from_dom = page.evaluate(f'''() => {{
                const links = document.querySelectorAll(
                    'a[href*="/Singles/{expansion_slug}/"]'
                );
                const names = [];
                const seen = new Set();
                for (const link of links) {{
                    const href = link.getAttribute('href') || '';
                    const slug = href.split('/Singles/{expansion_slug}/')[1]?.split('?')[0];
                    if (slug && !seen.has(slug)) {{
                        seen.add(slug);
                        const text = link.textContent.trim();
                        if (text && text.length > 1) {{
                            names.push({{slug: slug, name: text}});
                        }}
                    }}
                }}
                return names;
            }}''')
            if names_from_dom:
                page_cards = names_from_dom
        except Exception:
            pass

    # Pair product IDs with card slugs/names
    paired = min(len(page_product_ids), len(page_cards))
    for i in range(paired):
        results.append({
            "id_product": int(page_product_ids[i]),
            "slug": f"{expansion_slug}/{page_cards[i]['slug']}",
            "name": page_cards[i].get("name", ""),
        })

    return results


_BLOCKED = None  # Sentinel: Cloudflare blocked


def scrape_expansion(page: Page, slug: str):
    """Scrape all singles from one expansion.

    Returns:
        list[dict] — products found (may be empty for legitimate empty expansions)
        None — if blocked by Cloudflare
    """
    base_url = f"{CM_BASE}/{LOCALE}/Pokemon/Products/Singles/{slug}"
    all_products: list[dict] = []

    # Use list mode (more compact, more products per page)
    list_url = f"{base_url}?mode=list"
    page.goto(list_url, timeout=60000, wait_until="domcontentloaded")
    _delay(3, 5)

    if not _wait_for_page(page, timeout_sec=120):
        title = "?"
        try:
            title = page.title()
        except Exception:
            pass
        print(f"    BLOCKED by Cloudflare on {slug} (title={title})")
        return _BLOCKED

    _delay(2, 4)

    # Detect total pages
    html = page.content()
    total_pages = 1
    m = re.search(r"Page\s+\d+\s+of\s+(\d+)", html)
    if m:
        total_pages = int(m.group(1))

    for page_num in range(1, total_pages + 1):
        if page_num > 1:
            url = f"{base_url}?mode=list&site={page_num}"
            _delay(6, 12)
            page.goto(url, timeout=60000, wait_until="domcontentloaded")

            if not _wait_for_page(page, timeout_sec=90):
                print(f"    BLOCKED on page {page_num}")
                break
            _delay(2, 4)

        products = _extract_products_from_page(page, slug)
        all_products.extend(products)

        if total_pages > 1:
            print(f"    Page {page_num}/{total_pages}: {len(products)} products")

    return all_products


def discover_expansions(page: Page) -> list[str]:
    """Scrape the Expansions page to get ALL expansion slugs."""
    print("Loading Expansions page...")
    page.goto(f"{CM_BASE}/{LOCALE}/Pokemon/Expansions",
              timeout=60000, wait_until="domcontentloaded")

    if not _wait_for_page(page, timeout_sec=120):
        print("ERROR: Cloudflare blocked the Expansions page.")
        return []

    _delay(2, 4)

    html = page.content()
    raw = re.findall(
        rf'href="/{LOCALE}/Pokemon/Expansions/([A-Za-z0-9][A-Za-z0-9\-]*)"',
        html,
    )
    slugs = list(dict.fromkeys(raw))  # unique, preserve order
    print(f"  Found {len(slugs)} expansion slugs")
    return slugs


def save_progress(data: dict) -> None:
    """Save current progress to JSON."""
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape CardMarket product IDs via CDP")
    parser.add_argument("--resume", action="store_true", help="Resume from last save")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing progress
    all_products: dict[str, dict] = {}  # idProduct → {name, slug, expansion}
    scraped_expansions: set[str] = set()
    expansion_slugs: list[str] = []

    if args.resume and OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            all_products = data.get("products", {})
            scraped_expansions = set(data.get("scraped_expansions", []))
            expansion_slugs = data.get("expansion_slugs", [])
        print(f"Resuming: {len(all_products)} products, "
              f"{len(scraped_expansions)} expansions done")

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
    print("Chrome opened with CardMarket.")
    print("If Cloudflare challenge appears — solve it in the browser!")
    print("Waiting for page to load (up to 3 minutes)...")
    print("=" * 60)

    # Wait for Chrome to pass Cloudflare
    for i in range(180):
        time.sleep(1)
        try:
            with sync_playwright() as p_check:
                br = p_check.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
                pg = br.contexts[0].pages[0] if br.contexts[0].pages else None
                if pg:
                    title = pg.title()
                    url = pg.url
                    br.close()
                    if ("cardmarket.com" in url
                            and "Waiting" not in title
                            and "Just a moment" not in title
                            and "Access denied" not in title):
                        print(f"\n  CardMarket loaded! ({title})")
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

    # Connect via CDP and start scraping
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        print(f"\nConnected! Page: {page.title()}")
        print(f"URL: {page.url}\n")

        # Discover all expansions (or use cached list)
        if not expansion_slugs:
            expansion_slugs = discover_expansions(page)
            if not expansion_slugs:
                print("ERROR: No expansions found.")
                browser.close()
                chrome_proc.terminate()
                return
            # Save slug list immediately
            save_progress({
                "total_products": len(all_products),
                "scraped_expansions": sorted(scraped_expansions),
                "expansion_slugs": expansion_slugs,
                "products": all_products,
            })

        remaining = [s for s in expansion_slugs if s not in scraped_expansions]
        print(f"\nExpansions: {len(expansion_slugs)} total, "
              f"{len(scraped_expansions)} done, {len(remaining)} remaining\n")

        # Scrape each expansion
        total_new = 0
        consecutive_blocks = 0

        for idx, exp_slug in enumerate(remaining):
            print(f"[{len(scraped_expansions)+1}/{len(expansion_slugs)}] {exp_slug}")

            try:
                products = scrape_expansion(page, exp_slug)
            except Exception as e:
                err_str = str(e)
                if "interrupted by another navigation" in err_str:
                    # Cloudflare redirect conflict — wait and navigate to safe page
                    print(f"    Navigation conflict (Cloudflare redirect)")
                    _delay(5, 10)
                    try:
                        page.goto(f"{CM_BASE}/{LOCALE}/Pokemon",
                                  timeout=30000, wait_until="domcontentloaded")
                        _wait_for_page(page, timeout_sec=60)
                        _delay(5, 10)
                    except Exception:
                        pass
                else:
                    print(f"    ERROR: {e}")
                _delay(10, 20)
                continue

            # _BLOCKED (None) = Cloudflare blocked us
            if products is _BLOCKED:
                consecutive_blocks += 1
                if consecutive_blocks > 10:
                    print("\nToo many blocks. Run with --resume to continue later.")
                    break
                wait = 60 + consecutive_blocks * 30
                print(f"    BLOCKED ({consecutive_blocks}/10) — pausing {wait}s...")
                print(f"    If Cloudflare challenge appears in Chrome, solve it!")
                time.sleep(wait)

                # Navigate to a safe page first to clear Cloudflare state
                try:
                    page.goto(f"{CM_BASE}/{LOCALE}/Pokemon",
                              timeout=30000, wait_until="domcontentloaded")
                    if _wait_for_page(page, timeout_sec=120):
                        print(f"    Cloudflare cleared! Resuming...")
                        consecutive_blocks = max(0, consecutive_blocks - 1)
                        _delay(5, 10)
                    else:
                        print(f"    Still blocked, will retry...")
                except Exception:
                    pass
                continue

            # Empty list = legitimate empty expansion (no singles)
            consecutive_blocks = 0

            # Store products
            new_count = 0
            for prod in products:
                pid = str(prod["id_product"])
                if pid not in all_products:
                    new_count += 1
                all_products[pid] = {
                    "name": prod.get("name", ""),
                    "slug": prod.get("slug", ""),
                    "expansion": exp_slug,
                }
            total_new += new_count

            scraped_expansions.add(exp_slug)

            # Save after each expansion
            save_progress({
                "total_products": len(all_products),
                "scraped_expansions": sorted(scraped_expansions),
                "expansion_slugs": expansion_slugs,
                "products": all_products,
            })

            if products:
                print(f"    {len(products)} products ({new_count} new) | "
                      f"Total: {len(all_products)}")
            else:
                print(f"    Empty expansion (no singles) | Total: {len(all_products)}")

            # Rate limiting — increase delays progressively
            expansions_done = len(scraped_expansions)
            if expansions_done % 50 == 0 and expansions_done > 0:
                # Long break every 50 expansions to avoid Cloudflare
                print(f"\n    === Long break (2 min) after {expansions_done} expansions ===")
                time.sleep(120)
            elif expansions_done % 20 == 0 and expansions_done > 0:
                # Medium break every 20 expansions
                _delay(20, 30)
            else:
                _delay(8, 15)

        browser.close()

    print(f"\n{'='*60}")
    print(f"Done! {len(all_products)} total products in {OUTPUT_FILE}")
    print(f"  New this session: {total_new}")
    print(f"  Expansions scraped: {len(scraped_expansions)}/{len(expansion_slugs)}")
    print(f"\nNext step: run  python scripts/match_cm_products.py  to update the database")


if __name__ == "__main__":
    main()
