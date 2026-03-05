from __future__ import annotations

"""
Generate CardMarket URLs for identified cards.

Two strategies:
1. **idProduct redirect** (preferred) — CardMarket supports
   ``/Products?idProduct={id}`` which auto-redirects to the exact product page.
   Works for all EN cards that have a cm_id_product (~81% of the database).
2. **Search URL** (fallback) — opens CardMarket search filtered by card name.
   Used for cards without a cm_id_product (JP/TW cards, or missing data).

CardMarket locales: en, de, fr, es, it, pt, nl, pl, se, jp
"""

import re
import urllib.parse

# CardMarket base URL — locale is inserted dynamically
CM_BASE = "https://www.cardmarket.com"

# idCategory for Pokemon Singles
CM_POKEMON_SINGLES_CATEGORY = 51

# Default locale
DEFAULT_LOCALE = "en"


def _clean_card_name(name: str) -> str:
    """Remove ability/attack text in brackets from the card name.

    'Mega Gengar ex [Shadowy Concealment | Void Gale]' → 'Mega Gengar ex'
    'Pikachu (25/25)' → 'Pikachu'
    """
    # Remove [ability | attack]
    name = re.sub(r"\s*\[.*?\]", "", name)
    # Remove (NN/MM) set numbers
    name = re.sub(r"\s*\(\d+/\d+\)", "", name)
    # Remove other parenthetical notes
    name = re.sub(r"\s*\(.*?\)", "", name)
    return name.strip()


def search_url(
    card_name: str,
    expansion_id: int | None = None,
    locale: str = DEFAULT_LOCALE,
) -> str:
    """Build a CardMarket search URL for a card.

    This is the most reliable method — it always works and CardMarket's
    search is very precise. When expansion_id is provided, it further
    narrows the results.

    Args:
        card_name: Full card name (abilities will be stripped automatically).
        expansion_id: CardMarket expansion ID (idExpansion) for filtering.
        locale: CardMarket locale (en, de, fr, es, it, etc.).

    Returns:
        Full CardMarket search URL.
    """
    clean_name = _clean_card_name(card_name)

    params = {"searchString": clean_name}
    if expansion_id:
        params["idExpansion"] = str(expansion_id)
        params["idCategory"] = str(CM_POKEMON_SINGLES_CATEGORY)

    query = urllib.parse.urlencode(params)
    return f"{CM_BASE}/{locale}/Pokemon/Products/Search?{query}"


def card_url(
    card: dict,
    locale: str = DEFAULT_LOCALE,
) -> str:
    """Generate the best available CardMarket URL for a card.

    Priority:
    1. **idProduct redirect** — ``?idProduct={id}`` auto-redirects to product page.
       Works for all cards with a cm_id_product / id_product.
    2. **Search URL** — fallback for cards without a product ID.
       For JP/TW cards, uses eng_name + set abbreviation + collector number
       (e.g. "Charizard ex sv2a 006") which CardMarket handles well.

    Args:
        card: Card dict. Should have 'cm_id_product' or 'id_product' for direct
              links, otherwise falls back to search using 'name'/'eng_name'.
        locale: CardMarket locale.

    Returns:
        CardMarket URL (direct redirect or search).
    """
    # 1. idProduct redirect — auto-redirects to exact product page.
    #    cm_id_product is now unique per card (duplicates cleaned), so this
    #    is the most reliable method. Works for EN cards with a valid product ID.
    lang = card.get("language", "en")
    cm_id = card.get("cm_id_product") or card.get("id_product")
    if cm_id and str(cm_id).isdigit():
        return f"{CM_BASE}/{locale}/Pokemon/Products?idProduct={cm_id}"

    # 2. Fall back to search URL
    #    Use cm_expansion_id (CardMarket numeric ID) for filtering — NOT tcgdex set codes
    if lang in ("ja", "zh-tw"):
        search_name = card.get("eng_name") or card.get("name", "")
    else:
        search_name = card.get("name", "")
    search_name = _clean_card_name(search_name)

    # Append set abbreviation and collector number for more precise search.
    # Use abbreviation (e.g. "HIF") instead of set_id (e.g. "sm115") because
    # CardMarket recognises its own abbreviations but not tcgdex set codes.
    set_abbr = card.get("abbreviation", "")
    set_id = card.get("set_id", "")
    collector_num = card.get("collector_number")
    # Prefer abbreviation; fall back to cleaned set_id
    display_set = set_abbr or re.sub(r"^(tw-|jp-)", "", set_id)
    if display_set and collector_num is not None:
        try:
            num_str = f"{int(collector_num):03d}"
        except (ValueError, TypeError):
            num_str = str(collector_num)
        search_name = f"{search_name} {display_set} {num_str}"
    elif display_set:
        search_name = f"{search_name} {display_set}"

    params: dict[str, str] = {"searchString": search_name}
    # Only use cm_expansion_id for EN cards — for JP/TW it's inherited from EN
    # products and would incorrectly filter results to the wrong set
    if lang == "en":
        expansion_id = card.get("cm_expansion_id") or card.get("expansion_id")
        if expansion_id:
            params["idExpansion"] = str(expansion_id)
            params["idCategory"] = str(CM_POKEMON_SINGLES_CATEGORY)

    query = urllib.parse.urlencode(params)
    return f"{CM_BASE}/{locale}/Pokemon/Products/Search?{query}"


def card_urls_multi_locale(
    card: dict,
    locales: list[str] | None = None,
) -> dict[str, str]:
    """Generate CardMarket URLs for a card in multiple locales.

    Args:
        card: Card dict.
        locales: List of locale codes. Defaults to ['en', 'it', 'de', 'fr'].

    Returns:
        Dict of {locale: url}.
    """
    if locales is None:
        locales = ["en", "it", "de", "fr"]

    return {locale: card_url(card, locale=locale) for locale in locales}
