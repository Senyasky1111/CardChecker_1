"""
Generate eBay search URLs for Pokemon cards.

Produces a search URL filtered to sold/completed listings so the user
can see actual recent sale prices directly on eBay.

Category 183454 = Pokemon Individual Cards on eBay.
"""

from __future__ import annotations

import re
import urllib.parse


EBAY_BASE = "https://www.ebay.com/sch/i.html"
POKEMON_CARDS_CATEGORY = "183454"


def _clean_name(name: str) -> str:
    """Strip brackets, parenthetical notes, and special chars for search."""
    name = re.sub(r"\s*\[.*?\]", "", name)
    name = re.sub(r"\s*\(\d+/\d+\)", "", name)
    name = re.sub(r"\s*\(.*?\)", "", name)
    # Remove special unicode chars that confuse eBay search
    name = re.sub(r"[^\w\s\-'.&é]", "", name, flags=re.UNICODE)
    return name.strip()


def ebay_sold_url(card: dict) -> str:
    """Build an eBay sold-listings search URL for a card.

    Args:
        card: Card dict with keys: name, eng_name, language,
              collector_number, set_total, abbreviation.

    Returns:
        eBay URL filtered to completed/sold listings.
    """
    lang = card.get("language", "en")

    # Pick best name for search
    if lang in ("ja", "zh-tw"):
        name = card.get("eng_name") or card.get("name", "")
    else:
        name = card.get("name") or card.get("eng_name", "")

    name = _clean_name(name)
    if not name:
        return ""

    # Build search query parts
    parts = ["Pokemon", name]

    # Add language tag for non-EN cards
    if lang == "ja":
        parts.insert(1, "Japanese")
    elif lang == "zh-tw":
        parts.insert(1, "Chinese")

    # Add collector number (e.g. "006/078")
    number = card.get("collector_number")
    total = card.get("set_total")
    if number:
        if total:
            parts.append(f"{number:03d}/{total:03d}")
        else:
            parts.append(f"{number:03d}")

    query = " ".join(parts)

    params = {
        "_nkw": query,
        "_sacat": POKEMON_CARDS_CATEGORY,
        "LH_Sold": "1",
        "LH_Complete": "1",
    }

    return f"{EBAY_BASE}?{urllib.parse.urlencode(params)}"
