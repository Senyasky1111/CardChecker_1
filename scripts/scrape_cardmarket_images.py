from __future__ import annotations

"""
Scrape card images from CardMarket product pages.

Reads card list from data/cardmarket/cards_with_prices.json
(produced by download_cardmarket_csvs.py) and downloads images.

Rate limiting: 1.5s between requests (global lock across workers).
Workers: up to 3 concurrent threads.
Resumable: skips already-downloaded images.

Usage:
    python scripts/scrape_cardmarket_images.py
    python scripts/scrape_cardmarket_images.py --workers 1 --delay 2.0
"""

import argparse
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Optional

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Paths
DATA_DIR = Path("./data/cardmarket")
IMAGES_DIR = DATA_DIR / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# Scraper settings
BASE_URL = "https://www.cardmarket.com"
MAX_RETRIES = 3

# Global rate-limit state
_request_lock = Lock()
_last_request_time = 0.0


@dataclass
class ScrapeResult:
    id_product: int
    success: bool
    image_url: Optional[str] = None
    local_path: Optional[str] = None
    error: Optional[str] = None


class CardMarketImageScraper:
    """Download card images from CardMarket product pages."""

    def __init__(self, delay: float = 1.5):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
            }
        )

    def _rate_limit(self) -> None:
        """Global rate limiting across all workers."""
        global _last_request_time
        with _request_lock:
            elapsed = time.time() - _last_request_time
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)
            _last_request_time = time.time()

    # ------------------------------------------------------------------
    # Image URL extraction
    # ------------------------------------------------------------------

    _IMAGE_PATTERNS = [
        # og:image meta tag (most reliable)
        re.compile(
            r'<meta\s+property="og:image"\s+content="([^"]+)"', re.IGNORECASE
        ),
        # Front-face card image
        re.compile(
            r'<img[^>]+src="(https://static\.cardmarket\.com/img/[^"]+)"'
            r'[^>]*class="[^"]*is-front',
            re.IGNORECASE,
        ),
        re.compile(
            r'<img[^>]+class="[^"]*is-front[^"]*"'
            r'[^>]+src="(https://static\.cardmarket\.com/img/[^"]+)"',
            re.IGNORECASE,
        ),
        # data-src lazy load
        re.compile(
            r'data-src="(https://static\.cardmarket\.com/img/[^"]+)"',
            re.IGNORECASE,
        ),
        # Generic cardmarket image
        re.compile(
            r'src="(https://static\.cardmarket\.com/img/[^"]+\.(?:jpg|png|webp))"',
            re.IGNORECASE,
        ),
    ]

    def _extract_image_url(self, html: str) -> Optional[str]:
        """Try multiple regex patterns to find the card image URL."""
        for pattern in self._IMAGE_PATTERNS:
            match = pattern.search(html)
            if match:
                url = match.group(1)
                if "cardmarket.com" in url:
                    return url
        return None

    # ------------------------------------------------------------------
    # Scrape single card
    # ------------------------------------------------------------------

    def scrape_card(self, id_product: int) -> ScrapeResult:
        """Download the image for a single card by product ID."""
        local_path = IMAGES_DIR / f"{id_product}.jpg"

        # Already downloaded?
        if local_path.exists() and local_path.stat().st_size > 0:
            return ScrapeResult(
                id_product=id_product,
                success=True,
                local_path=str(local_path),
            )

        product_url = (
            f"{BASE_URL}/en/Pokemon/Products/Singles/"
            f"Product?idProduct={id_product}"
        )

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._rate_limit()
                resp = self.session.get(product_url, timeout=30)

                if resp.status_code == 429:
                    logger.warning("Rate-limited (429). Sleeping 60 s...")
                    time.sleep(60)
                    continue

                if resp.status_code == 404:
                    return ScrapeResult(
                        id_product=id_product,
                        success=False,
                        error="404 Not Found",
                    )

                resp.raise_for_status()
                image_url = self._extract_image_url(resp.text)

                if not image_url:
                    return ScrapeResult(
                        id_product=id_product,
                        success=False,
                        error="Image URL not found in HTML",
                    )

                # Download image
                self._rate_limit()
                img_resp = self.session.get(image_url, timeout=30)
                img_resp.raise_for_status()

                local_path.write_bytes(img_resp.content)
                return ScrapeResult(
                    id_product=id_product,
                    success=True,
                    image_url=image_url,
                    local_path=str(local_path),
                )

            except requests.exceptions.Timeout:
                logger.warning(
                    "Timeout for %d (attempt %d/%d)",
                    id_product,
                    attempt,
                    MAX_RETRIES,
                )
                time.sleep(5)
            except Exception as exc:
                logger.error("Error for %d: %s", id_product, exc)
                if attempt == MAX_RETRIES:
                    return ScrapeResult(
                        id_product=id_product,
                        success=False,
                        error=str(exc),
                    )
                time.sleep(5)

        return ScrapeResult(
            id_product=id_product,
            success=False,
            error="Max retries exceeded",
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def load_card_ids() -> list[int]:
    """Load card IDs from the merged JSON."""
    cards_file = DATA_DIR / "cards_with_prices.json"
    if not cards_file.exists():
        logger.error(
            "cards_with_prices.json not found. "
            "Run download_cardmarket_csvs.py first."
        )
        raise SystemExit(1)

    with open(cards_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return [c["id_product"] for c in data["cards"]]


def save_progress(results: list[ScrapeResult]) -> None:
    """Persist scrape progress to JSON."""
    progress = {
        "total": len(results),
        "success": sum(1 for r in results if r.success),
        "failed": sum(1 for r in results if not r.success),
        "results": [
            {
                "id_product": r.id_product,
                "success": r.success,
                "image_url": r.image_url,
                "local_path": r.local_path,
                "error": r.error,
            }
            for r in results
        ],
    }
    with open(DATA_DIR / "scrape_progress.json", "w") as f:
        json.dump(progress, f, indent=2)


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape CardMarket images")
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Number of concurrent workers (default: 3)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Seconds between requests (default: 1.5)",
    )
    args = parser.parse_args()

    all_ids = load_card_ids()
    logger.info("Total cards in dataset: %d", len(all_ids))

    # Filter out already-downloaded
    already = set()
    for img_file in IMAGES_DIR.glob("*.jpg"):
        try:
            already.add(int(img_file.stem))
        except ValueError:
            pass

    ids_to_scrape = [i for i in all_ids if i not in already]
    logger.info("Already downloaded: %d", len(already))
    logger.info("Remaining to scrape: %d", len(ids_to_scrape))

    if not ids_to_scrape:
        logger.info("All images already downloaded!")
        return

    est_seconds = len(ids_to_scrape) * args.delay * 2 / args.workers
    est_hours = est_seconds / 3600
    logger.info(
        "Estimated time: %.1f hours (%.0f min)", est_hours, est_seconds / 60
    )

    scraper = CardMarketImageScraper(delay=args.delay)
    results: list[ScrapeResult] = []
    success_count = 0
    fail_count = 0

    from tqdm import tqdm

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(scraper.scrape_card, pid): pid
            for pid in ids_to_scrape
        }

        pbar = tqdm(
            total=len(ids_to_scrape),
            desc="Scraping cards",
            unit="card",
        )

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

            if result.success:
                success_count += 1
            else:
                fail_count += 1
                logger.debug(
                    "FAIL %d: %s", result.id_product, result.error
                )

            pbar.set_postfix(ok=success_count, fail=fail_count)
            pbar.update(1)

            if len(results) % 100 == 0:
                save_progress(results)

        pbar.close()

    save_progress(results)
    logger.info(
        "Done! %d/%d succeeded (%.1f%%)",
        success_count,
        len(results),
        success_count / max(len(results), 1) * 100,
    )


if __name__ == "__main__":
    main()
