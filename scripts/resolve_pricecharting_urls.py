"""Resolve PriceCharting URLs: generate direct URLs from set mappings,
validate via HTTP, fallback to search URL.

Combo approach:
1. For cards in mapped sets -> build direct URL /game/{prefix}-{set_slug}/{card_slug}-{num}
2. Validate with HEAD request -> if PC redirects to search, URL doesn't exist
3. If invalid or unmapped set -> keep search URL as fallback

Usage:
    python scripts/resolve_pricecharting_urls.py [--validate] [--batch N] [--lang ja|zh-tw|en] [--dry-run]

Options:
    --validate   Check direct URLs via HTTP (slower but accurate, ~0.3s/card)
    --batch N    Process N cards then stop (for incremental runs)
    --lang       Only process one language
    --dry-run    Don't write to DB, just show stats
"""

from __future__ import annotations

import argparse
import io
import re
import sqlite3
import sys
import time
from pathlib import Path
from random import uniform

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.build_pricecharting_map import (
    EN_SET_SLUGS,
    JP_SET_SLUGS,
    TW_SET_SLUGS,
    PC_BASE,
    slugify_card_name,
    build_pricecharting_url,
)
from src.db import ensure_schema

# build_pricecharting_map wraps sys.stdout at import time.
# Re-wrap from the underlying raw stream to ensure it's usable.
sys.stdout = io.TextIOWrapper(
    open(sys.stdout.fileno(), "wb", closefd=False),
    encoding="utf-8",
    errors="replace",
    line_buffering=True,
)


def _build_direct_url(card: dict) -> str | None:
    """Try to build a direct PriceCharting URL from set mapping.

    Returns URL string if set is mapped, None otherwise.
    """
    lang = card.get("language", "en")
    set_id = card.get("set_id", "")
    name = (card.get("eng_name") or card.get("name", "")).strip()
    number = card.get("collector_number")

    if not name:
        return None

    if lang == "en":
        slug_map = EN_SET_SLUGS
        prefix = "pokemon"
    elif lang == "ja":
        slug_map = JP_SET_SLUGS
        prefix = "pokemon-japanese"
    elif lang == "zh-tw":
        slug_map = TW_SET_SLUGS
        prefix = "pokemon-chinese"
    else:
        return None

    set_slug = slug_map.get(set_id)
    if not set_slug:
        return None

    card_slug = slugify_card_name(name)
    if not card_slug:
        return None

    if number is not None:
        try:
            num = int(number)
            card_slug = f"{card_slug}-{num}"
        except (ValueError, TypeError):
            card_slug = f"{card_slug}-{number}"

    return f"{PC_BASE}/game/{prefix}-{set_slug}/{card_slug}"


def _validate_url(session: requests.Session, url: str) -> bool:
    """Check if a PriceCharting direct URL actually exists.

    PC returns 200 + redirects to search page when the URL doesn't exist.
    """
    try:
        r = session.get(url, timeout=10, allow_redirects=True)
        # If final URL still contains /game/ and NOT /search, it exists
        return "/game/" in r.url and "/search" not in r.url
    except Exception:
        return False


def resolve_urls(
    conn: sqlite3.Connection,
    validate: bool = False,
    batch: int = 0,
    lang_filter: str | None = None,
    dry_run: bool = False,
):
    """Resolve PriceCharting URLs for all cards."""
    conn.row_factory = sqlite3.Row

    session = None
    if validate:
        session = requests.Session()
        session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

    languages = [("en", "EN"), ("ja", "JP"), ("zh-tw", "TW")]
    if lang_filter:
        languages = [(l, lab) for l, lab in languages if l == lang_filter]

    stats = {
        "direct_new": 0,
        "direct_validated": 0,
        "direct_invalid": 0,
        "search_kept": 0,
        "search_new": 0,
        "unchanged": 0,
        "total": 0,
    }
    processed = 0

    for lang, label in languages:
        cards = conn.execute(
            """
            SELECT c.tcgdex_id, c.name, c.eng_name, c.set_id,
                   c.collector_number, c.language, c.pricecharting_url,
                   s.name as set_name, s.abbreviation
            FROM cards c
            LEFT JOIN sets s ON c.set_id = s.set_id AND s.language = c.language
            WHERE c.language = ?
        """,
            (lang,),
        ).fetchall()

        direct_new = 0
        validated = 0
        invalid = 0
        search_kept = 0
        search_new = 0
        unchanged = 0
        http_errors = 0

        for i, card in enumerate(cards):
            if batch and processed >= batch:
                break

            d = dict(card)
            old_url = (d.get("pricecharting_url") or "").strip()

            # Try to build direct URL from mapping
            direct = _build_direct_url(d)

            if direct:
                if validate:
                    # Check if URL actually exists on PC
                    try:
                        ok = _validate_url(session, direct)
                    except Exception as e:
                        ok = False
                        http_errors += 1
                        if http_errors <= 3:
                            print(f"  HTTP error: {e}")
                    time.sleep(uniform(0.2, 0.4))

                    if ok:
                        new_url = direct
                        validated += 1
                    else:
                        # Direct URL doesn't exist — use search fallback
                        new_url = build_pricecharting_url(d)
                        invalid += 1

                    # Progress log every 500 cards
                    if (i + 1) % 500 == 0:
                        print(
                            f"  {label} progress: {i+1}/{len(cards)} "
                            f"(valid={validated}, invalid={invalid}, "
                            f"errors={http_errors})"
                        )
                        sys.stdout.flush()
                else:
                    # Trust the mapping without HTTP validation
                    new_url = direct
                    direct_new += 1
            else:
                # No mapping — generate search URL
                new_url = build_pricecharting_url(d)
                if "/game/" in new_url:
                    direct_new += 1  # build_pricecharting_url found a mapping
                elif old_url and old_url == new_url:
                    unchanged += 1
                else:
                    search_new += 1

            # Write to DB if changed
            if new_url and new_url != old_url and not dry_run:
                conn.execute(
                    "UPDATE cards SET pricecharting_url = ? WHERE tcgdex_id = ?",
                    (new_url, d["tcgdex_id"]),
                )

            # Incremental commit every 1000 cards
            if not dry_run and (i + 1) % 1000 == 0:
                conn.commit()

            processed += 1

        if not dry_run:
            conn.commit()

        total_lang = len(cards)
        direct_count = direct_new + validated
        search_count = search_kept + search_new + invalid + unchanged

        print(f"\n{label}: {total_lang} cards")
        if validate:
            print(f"  Direct (validated): {validated}")
            print(f"  Direct (invalid -> search): {invalid}")
        else:
            print(f"  Direct (from mapping): {direct_new}")
        print(f"  Search URL: {search_count}")
        print(
            f"  Coverage: {direct_count}/{total_lang} "
            f"({100 * direct_count / total_lang:.1f}%) direct"
        )

        stats["direct_new"] += direct_new
        stats["direct_validated"] += validated
        stats["direct_invalid"] += invalid
        stats["search_kept"] += search_kept
        stats["search_new"] += search_new
        stats["unchanged"] += unchanged
        stats["total"] += len(cards)

        if batch and processed >= batch:
            print(f"\n  (stopped at batch limit {batch})")
            break

    total_direct = stats["direct_new"] + stats["direct_validated"]
    print(f"\n{'='*50}")
    print(f"TOTAL: {stats['total']} cards")
    print(f"  Direct URLs: {total_direct} ({100 * total_direct / stats['total']:.1f}%)")
    print(
        f"  Search URLs: {stats['total'] - total_direct} "
        f"({100 * (stats['total'] - total_direct) / stats['total']:.1f}%)"
    )
    if validate:
        print(f"  Invalid (fell back to search): {stats['direct_invalid']}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Resolve PriceCharting URLs")
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate direct URLs via HTTP (slower)",
    )
    parser.add_argument(
        "--batch", type=int, default=0, help="Process N cards then stop"
    )
    parser.add_argument("--lang", choices=["en", "ja", "zh-tw"], help="Only one language")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = ensure_schema()
    print("=== Resolving PriceCharting URLs ===")
    if args.validate:
        print("Mode: generate + HTTP validate")
    else:
        print("Mode: generate from mappings (no HTTP)")
    print()

    resolve_urls(
        conn,
        validate=args.validate,
        batch=args.batch,
        lang_filter=args.lang,
        dry_run=args.dry_run,
    )
    conn.close()


if __name__ == "__main__":
    main()
