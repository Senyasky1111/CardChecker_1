"""Build PriceCharting set slug mapping and generate URLs for all cards.

PriceCharting URL structure:
  EN: /game/pokemon-{set-slug}/{card-name-slug}-{number}
  JP: /game/pokemon-japanese-{set-slug}/{card-name-slug}-{number}
  TW: /game/pokemon-chinese-{set-slug}/{card-name-slug}-{number}

Strategy:
1. Scrape PriceCharting category pages to get all set slugs
2. Map our set_id/set_name to PriceCharting slugs
3. Generate and validate URLs
4. Store in database

Usage:
    python scripts/build_pricecharting_map.py [--scrape] [--fill] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import io
import time
from pathlib import Path
from urllib.parse import quote

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.db import ensure_schema

PC_BASE = "https://www.pricecharting.com"
MAP_FILE = Path("data/cardmarket/_pricecharting_set_map.json")


# ── Known set slug mappings ──────────────────────────────────────────
# PriceCharting set slugs extracted from their category page
# Format: our_set_id -> pricecharting set slug (without the pokemon- prefix)

# These were manually extracted + web-scraped
EN_SET_SLUGS = {
    # Scarlet & Violet era
    "sv01": "scarlet-&-violet",
    "sv02": "paldea-evolved",
    "sv03": "obsidian-flames",
    "sv03.5": "scarlet-&-violet-151",
    "sv04": "paradox-rift",
    "sv04.5": "paldean-fates",
    "sv05": "temporal-forces",
    "sv06": "twilight-masquerade",
    "sv06.5": "shrouded-fable",
    "sv07": "stellar-crown",
    "sv08": "surging-sparks",
    "sv08.5": "prismatic-evolutions",
    "sv09": "journey-together",
    "sv10": "destined-rivals",
    "sv10.5b": "black-bolt",
    "sv10.5w": "white-flare",
    "svp": "promo",
    # Mega Evolution era
    "me01": "mega-evolution",
    "me02": "phantasmal-flames",
    "me02.5": "ascended-heroes",
    # Sword & Shield era
    "swsh1": "sword-&-shield",
    "swsh2": "rebel-clash",
    "swsh3": "darkness-ablaze",
    "swsh3.5": "champion%27s-path",
    "swsh4": "vivid-voltage",
    "swsh4.5": "shining-fates",
    "swsh5": "battle-styles",
    "swsh6": "chilling-reign",
    "swsh7": "evolving-skies",
    "swsh8": "fusion-strike",
    "swsh9": "brilliant-stars",
    "swsh10": "astral-radiance",
    "swsh10.5": "go",
    "swsh11": "lost-origin",
    "swsh12": "silver-tempest",
    "swsh12.5": "crown-zenith",
    "swshp": "promo",  # Note: overlaps with svp for "promo"
    "cel25": "celebrations",
    # Sun & Moon era
    "sm1": "sun-&-moon",
    "sm2": "guardians-rising",
    "sm3": "burning-shadows",
    "sm3.5": "shining-legends",
    "sm4": "crimson-invasion",
    "sm5": "ultra-prism",
    "sm6": "forbidden-light",
    "sm7": "celestial-storm",
    "sm7.5": "dragon-majesty",
    "sm8": "lost-thunder",
    "sm9": "team-up",
    "sm10": "unbroken-bonds",
    "sm11": "unified-minds",
    "sm115": "hidden-fates",
    "sm12": "cosmic-eclipse",
    "smp": "promo",
    "det1": "detective-pikachu",
    # XY era
    "xy1": "xy",
    "xy2": "flashfire",
    "xy3": "furious-fists",
    "xy4": "phantom-forces",
    "xy5": "primal-clash",
    "xy6": "roaring-skies",
    "xy7": "ancient-origins",
    "xy8": "breakthrough",
    "xy9": "breakpoint",
    "xy10": "fates-collide",
    "xy11": "steam-siege",
    "xy12": "evolutions",
    "xyp": "promo",
    "g1": "generations",
    "dc1": "double-crisis",
    # BW era
    "bw1": "black-&-white",
    "bw2": "emerging-powers",
    "bw3": "noble-victories",
    "bw4": "next-destinies",
    "bw5": "dark-explorers",
    "bw6": "dragons-exalted",
    "bw7": "boundaries-crossed",
    "bw8": "plasma-storm",
    "bw9": "plasma-freeze",
    "bw10": "plasma-blast",
    "bw11": "legendary-treasures",
    "bwp": "promo",
    "dv1": "dragon-vault",
    # Diamond & Pearl / Platinum era
    "dp1": "diamond-&-pearl",
    "dp2": "mysterious-treasures",
    "dp3": "secret-wonders",
    "dp4": "great-encounters",
    "dp5": "majestic-dawn",
    "dp6": "legends-awakened",
    "dp7": "stormfront",
    "dpp": "promo",
    "pl1": "platinum",
    "pl2": "rising-rivals",
    "pl3": "supreme-victors",
    "pl4": "arceus",
    # HGSS era
    "hgss1": "heartgold-&-soulsilver",
    "hgss2": "unleashed",
    "hgss3": "undaunted",
    "hgss4": "triumphant",
    "col1": "call-of-legends",
    # EX era
    "ex1": "ruby-&-sapphire",
    "ex2": "sandstorm",
    "ex3": "dragon",
    "ex4": "team-magma-&-team-aqua",
    "ex5": "hidden-legends",
    "ex6": "fire-red-&-leaf-green",
    "ex7": "team-rocket-returns",
    "ex8": "deoxys",
    "ex9": "emerald",
    "ex10": "unseen-forces",
    "ex11": "delta-species",
    "ex12": "legend-maker",
    "ex13": "holon-phantoms",
    "ex14": "crystal-guardians",
    "ex15": "dragon-frontiers",
    "ex16": "power-keepers",
    # E-Card era
    "ecard1": "expedition",
    "ecard2": "aquapolis",
    "ecard3": "skyridge",
    # Classic era
    "base1": "base-set",
    "base2": "jungle",
    "base3": "fossil",
    "base4": "base-set-2",
    "base5": "team-rocket",
    "neo1": "neo-genesis",
    "neo2": "neo-discovery",
    "neo3": "neo-revelation",
    "neo4": "neo-destiny",
    "lc": "legendary-collection",
    "gym1": "gym-heroes",
    "gym2": "gym-challenge",
    "si1": "southern-islands",
    # Other
    "ru1": "rumble",
    "bog": "best-of-game",
}

# Japanese sets
JP_SET_SLUGS = {
    # ── SV era ──
    "SV1S": "scarlet-ex",
    "SV1V": "violet-ex",
    "SV1a": "triplet-beat",
    "SV2a": "scarlet-&-violet-151",
    "SV2P": "snow-hazard",
    "SV2D": "clay-burst",
    "SV3": "ruler-of-the-black-flame",
    "SV3a": "raging-surf",
    "SV4a": "shiny-treasure-ex",
    "SV4K": "ancient-roar",
    "SV4M": "future-flash",
    "SV5a": "crimson-haze",
    "SV5K": "wild-force",
    "SV5M": "cyber-judge",
    "SV6": "mask-of-change",
    "SV6a": "night-wanderer",
    "SV7": "stellar-miracle",
    "SV7a": "paradise-dragona",
    "SV8": "super-electric-breaker",
    "SV8a": "super-electric-breaker",
    "SV9": "paradise-dragona",
    "SV9a": "mega-symphonia",
    "SV10": "battle-partners",
    "SV11B": "black-bolt",
    "SV11W": "white-flare",
    "SV-P": "promo",
    "SVG": "svg-special-set",
    "SVM": "terastal-festival",
    # SV starter/special products
    "SVB": "bulbasaur-deck",
    "SVD": "ex-starter-decks",
    "SVF": "stellar-miracle-deck-build-box",
    "SVI": "battle-academy",
    "SVK": "stellar-miracle-deck-build-box",
    "SVN": "battle-partners-deck-build-box",
    "SVAL": "squirtle-deck",
    "SVAM": "movie-commemoration-vs-pack",
    "SVEM": "mewtwo-ex-starter-deck",
    "SVHK": "ancient-koraidon-ex-starter-deck",
    "SVHM": "future-miraidon-ex-starter-deck",
    "SVJP": "battle-master-chien-pao",
    "SVLN": "stellar-tera-starter-set-sylveon-ex",
    "SVLS": "stellar-tera-starter-set-ceruledge-ex",
    "SVOD": "starter-set-svod",
    "SVOM": "starter-set-svom",
    "SVP1": "ex-special-set",
    "SC": "shiny-collection",
    # ── Sword & Shield era ──
    "S12a": "vstar-universe",
    "S12": "paradigm-trigger",
    "S11": "paradigm-trigger",
    "S11a": "incandescent-arcana",
    "S10a": "dark-phantasma",
    "S10b": "go",
    "S10D": "time-gazer",
    "S10P": "space-juggler",
    "S9": "star-birth",
    "S9a": "battle-region",
    "S8b": "vmax-climax",
    "S8a": "25th-anniversary-collection",
    "S8a-G": "vstar-special-set",
    "S7R": "blue-sky-stream",
    "S7D": "towering-perfection",
    "S6a": "eevee-heroes",
    "S6H": "silver-lance",
    "S6K": "jet-black-spirit",
    "S5R": "rapid-strike-master",
    "S5I": "single-strike-master",
    "S5a": "matchless-fighter",
    "S4a": "shiny-star-v",
    "S4": "amazing-volt-tackle",
    "S3a": "legendary-heartbeat",
    "S3": "infinity-zone",
    "S2a": "explosive-walker",
    "S2": "rebellion-crash",
    "S1a": "vmax-rising",
    "S1H": "shield",
    "S1W": "sword",
    "S-P": "promo",
    "SO": "charizard-vmax-starter-set",
    "SP6": "vstar-special-set",
    # ── SM era ──
    "SM12a": "tag-all-stars",
    "SM12": "alter-genesis",
    "SM11b": "dream-league",
    "SM11a": "remix-bout",
    "SM11": "miracle-twins",
    "SM10b": "sky-legend",
    "SM10a": "gg-end",
    "SM10": "double-blaze",
    "SM9b": "full-metal-wall",
    "SM9a": "night-unison",
    "SM9": "tag-bolt",
    "SM8b": "gx-ultra-shiny",
    "SM8a": "dark-order",
    "SM8": "super-burst-impact",
    "SM7b": "fairy-rise",
    "SM7a": "thunderclap-spark",
    "SM7": "charisma-of-the-wrecked-sky",
    "SM6b": "champion-road",
    "SM6a": "dragon-storm",
    "SM6": "forbidden-light",
    "SM5p": "ultra-force",
    "SM5S": "ultra-sun",
    "SM5M": "ultra-moon",
    "SM4p": "gx-battle-boost",
    "SM4A": "the-best-of-xy",
    "SM4S": "awakened-heroes",
    "SM4": "the-best-of-xy",
    "SM3p": "shining-legends",
    "SM3N": "darkness-that-consumes-light",
    "SM3H": "to-have-seen-the-battle-rainbow",
    "SM2p": "alolan-moonlight",
    "SM2L": "alolan-moonlight",
    "SM2K": "islands-await-you",
    "SM1p": "premium-trainer-box",
    "SM1S": "sun-collection",
    "SM1M": "moon-collection",
    "SMP": "promo",
    "SMP2": "detective-pikachu",
    "SMI": "sm1",
    "SMK": "trainer-battle-decks",
    "SMN": "vending",
    # ── Mega Evolution era ──
    "M1L": "mega-brave",
    "M1S": "mega-symphonia",
    "M2": "inferno-x",
    "M2a": "mega-dream-ex",
    "M3": "nihil-zero",
    "MBD": "mega-starter-deck-diancie-ex",
    "MBG": "mega-starter-deck-gengar-ex",
    "MDB": "rayquaza-ex-mega-battle-deck",
    # ── XY era ──
    "XY": "xy",
    "XY9-B": "rage-of-the-broken-heavens",
    "XYA": "m-charizard-ex-mega-battle-deck",
    "XYB": "hyper-metal-chain-deck",
    "XYC": "super-legend",
    "XYD": "rayquaza-ex-mega-battle-deck",
    "Y30": "yveltal-half-deck",
    "X30": "yveltal-half-deck",
    # ── BW era ──
    "BW2-B": "red-collection",
    "BW4-B": "dark-rush",
    "BW8-Brf": "spiral-force",
    "BW9-B": "double-blaze",
    "BGSt": "battle-gift-set-thundurus-vs-tornadus",
    "BGSv": "battle-gift-set-thundurus-vs-tornadus",
    "BKB": "black-kyurem-ex-battle-strength-deck",
    "BKR": "squirtle-deck",
    "BKW": "white-kyurem-ex-battle-strength-deck",
    "BKZ": "zekrom-ex-battle-strength-deck",
    "BKt": "terrakion-battle-strength",
    "BKv": "v-starter-set-sa",
    "BTV": "rayquaza-ex-mega-battle-deck",
    "PBG": "team-plasma-battle-gift-set",
    # ── DP/Pt era ──
    "DPP": "entry-pack-2008",
    "DPt1-B": "galactic%27s-conquest",
    "DPt2-Se": "gallade-half-deck",
    "DPt3-Sg": "garchomp-sp-half-deck",
    "DPt3-Sl": "promo",
    "DPt-EPd": "entry-pack-dpt",
    "DPt-EPp": "entry-pack-dpt",
    "DPt-GBna": "vending",
    "DPt-GBpi": "melee-pokemon-scramble",
    "DPt-MRP09": "movie-commemoration-random",
    "DPs-Sd": "vending",
    "DPs-Sg": "feraligatr-starter-deck",
    # ── HGSS / Legend era ──
    "L1-Bss": "soulsilver-collection",
    "L2-Sb": "vending",
    "LL": "lost-link",
    "HSm": "beginning-set-hs",
    "HSp": "beginning-set-hs",
    "HSPm": "beginning-set-hs",
    "HSPp": "beginning-set-hs",
    "HSZm": "national-beginning",
    "HSZp": "beginning-set-hs",
    # ── Starter/special products ──
    "Bb": "battle-starter-decks",
    "Bd": "battle-starter-decks",
    "CP5": "dream-shine-collection",
    "CP6": "20th-anniversary",
    "CPm": "collection-pack",
    "CPr": "collection-pack",
    "CPs": "collection-pack",
    "CS1m": "journey-together-collection-sheet",
    "CS1p": "journey-together-collection-sheet",
    "CS1t": "journey-together-collection-sheet",
    "Em": "leafeon-vs-metagross-expert-deck",
    "El": "jet-black-spirit",
    "GBR": "garchomp-half-deck",
    "MPS08": "11th-movie-commemoration-promo",
    "MP1": "start-deck-100-battle-collection-corociao",
    "Ran": "melee-pokemon-scramble",
    "SGG": "gengar-vmax-high-class",
    "SLD": "darkrai-starter",
    "SLL": "lucario-starter",
    "SPD": "deoxys-high-class",
    "SPZ": "zeraora-high-class",
    "WCS23": "ex-special-set",
}

# Chinese sets — PriceCharting only has ~14 sets for Chinese cards
# PC slug codes: cs = Chinese S&S, csv = Chinese SV, csm = Chinese SM
TW_SET_SLUGS = {
    "tw-SV2a": "151-collect",
    "tw-MC": "gem-pack",
    "tw-SVM": "gem-pack-2",
    "tw-M2a": "gem-pack-3",
    "tw-M3": "gem-pack-4",
    "tw-SV4a": "csv4c",
    "tw-SV8a": "csv8c",
    "tw-AC2a": "cs4ac",
    "tw-AC2b": "cs4bc",
    "tw-AS5a": "csm2ac",   # SM2 era set a
    "tw-AS5b": "csm2bc",   # SM2 era set b
    "tw-AS6a": "csm2cc",   # SM2 era set c
    "tw-M2": "m2f",
    "tw-SV-P": "promo",
}


def slugify_card_name(name: str) -> str:
    """Convert card name to PriceCharting URL slug."""
    # Remove ability/attack text
    name = re.sub(r"\s*\[.*?\]", "", name)
    name = re.sub(r"\s*\(.*?\)", "", name)
    # Lowercase
    slug = name.lower().strip()
    # Replace special chars with hyphens
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug


def build_pricecharting_url(card: dict) -> str:
    """Build PriceCharting URL for a card.

    Strategy:
    1. Direct URL if set is mapped: /game/pokemon-{set}/{card}-{num}
    2. Search URL fallback for all others: /search-products?q={name+set}&type=prices

    Always returns a URL (never empty for cards with a name).
    """
    lang = card.get("language", "en")
    set_id = card.get("set_id", "")
    name = (card.get("eng_name") or card.get("name", "")).strip()
    number = card.get("collector_number")
    set_name = card.get("set_name", "")

    if not name:
        return ""

    # Determine language prefix and slug map
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
        return ""

    set_slug = slug_map.get(set_id)

    if set_slug:
        # Strategy 1: Direct URL
        card_slug = slugify_card_name(name)
        if not card_slug:
            return _build_search_url(name, _search_set_info(card, lang), lang, number)

        if number is not None:
            try:
                num = int(number)
                card_slug = f"{card_slug}-{num}"
            except (ValueError, TypeError):
                card_slug = f"{card_slug}-{number}"

        return f"{PC_BASE}/game/{prefix}-{set_slug}/{card_slug}"
    else:
        # Strategy 2: Search URL fallback
        return _build_search_url(name, _search_set_info(card, lang), lang, number)


def _search_set_info(card: dict, lang: str) -> str:
    """Get best set identifier for PriceCharting search.

    For EN: use set_name (English name).
    For JP/TW: use abbreviation code (e.g. SV5K) since CJK set names
    don't work on PriceCharting's English search.
    """
    if lang == "en":
        return card.get("set_name") or card.get("set_id", "")

    # JP/TW: prefer abbreviation (short code), fall back to cleaned set_id
    abbr = (card.get("abbreviation") or "").strip()
    if abbr:
        return abbr

    # Strip tw-/jp- prefix from set_id
    sid = card.get("set_id", "")
    return re.sub(r"^(tw-|jp-)", "", sid)


def _build_search_url(name: str, set_info: str, lang: str, number=None) -> str:
    """Build PriceCharting search URL as fallback."""
    from urllib.parse import quote_plus

    # Clean name
    clean_name = re.sub(r"\s*\[.*?\]", "", name)
    clean_name = re.sub(r"\s*\(.*?\)", "", clean_name).strip()

    # Build search query
    parts = [clean_name]

    # Add set info — only for EN cards where it's an English name that PC recognizes.
    # For JP/TW, abbreviation codes (M1L, SV5K) confuse PriceCharting search,
    # so we rely on name + number + language keyword instead.
    if set_info and lang == "en":
        parts.append(set_info)

    # Add number for disambiguation
    if number is not None:
        try:
            parts.append(str(int(number)))
        except (ValueError, TypeError):
            pass

    # Add language context
    if lang == "ja":
        parts.append("japanese")
    elif lang == "zh-tw":
        parts.append("chinese")

    query = " ".join(parts)
    return f"{PC_BASE}/search-products?q={quote_plus(query)}&type=prices"


def scrape_pricecharting_sets():
    """Scrape PriceCharting to get all available set slugs."""
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    print("Scraping PriceCharting category page...")
    r = session.get(f"{PC_BASE}/category/pokemon-cards", timeout=15)
    if r.status_code != 200:
        print(f"  Error: {r.status_code}")
        return

    # Extract all set slugs from the page
    slugs = re.findall(r'/console/(pokemon-[^"\'?#\s]+)', r.text)
    unique_slugs = sorted(set(slugs))

    print(f"  Found {len(unique_slugs)} set slugs")

    en_slugs = []
    jp_slugs = []
    cn_slugs = []
    kr_slugs = []

    for s in unique_slugs:
        if s.startswith("pokemon-japanese-"):
            jp_slugs.append(s.replace("pokemon-japanese-", ""))
        elif s.startswith("pokemon-chinese-"):
            cn_slugs.append(s.replace("pokemon-chinese-", ""))
        elif s.startswith("pokemon-korean-"):
            kr_slugs.append(s.replace("pokemon-korean-", ""))
        elif s.startswith("pokemon-"):
            en_slugs.append(s.replace("pokemon-", ""))

    print(f"  EN: {len(en_slugs)} | JP: {len(jp_slugs)} | CN: {len(cn_slugs)} | KR: {len(kr_slugs)}")

    return {
        "en": en_slugs,
        "ja": jp_slugs,
        "zh-tw": cn_slugs,
        "ko": kr_slugs,
    }


def fill_pricecharting_urls(conn, dry_run: bool = False):
    """Fill pricecharting_url column for all cards."""
    # Ensure column exists
    try:
        conn.execute("ALTER TABLE cards ADD COLUMN pricecharting_url TEXT DEFAULT ''")
        conn.commit()
        print("  Added pricecharting_url column")
    except Exception:
        pass  # Column already exists

    filled = {"en": 0, "ja": 0, "zh-tw": 0}
    total = {"en": 0, "ja": 0, "zh-tw": 0}

    for lang, label in [("en", "EN"), ("ja", "JP"), ("zh-tw", "TW")]:
        cards = conn.execute("""
            SELECT c.tcgdex_id, c.name, c.eng_name, c.set_id, c.collector_number, c.language,
                   s.name as set_name, s.abbreviation as abbreviation
            FROM cards c
            LEFT JOIN sets s ON c.set_id = s.set_id AND s.language = c.language
            WHERE c.language = ?
        """, (lang,)).fetchall()

        total[lang] = len(cards)
        for card in cards:
            url = build_pricecharting_url(dict(card))
            if url:
                if not dry_run:
                    conn.execute("UPDATE cards SET pricecharting_url = ? WHERE tcgdex_id = ?",
                                 (url, card["tcgdex_id"]))
                filled[lang] += 1

        if not dry_run:
            conn.commit()
        print(f"  {label}: {filled[lang]}/{total[lang]} ({100*filled[lang]/total[lang]:.1f}%) URLs generated")

    return filled, total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scrape", action="store_true", help="Scrape PriceCharting for set slugs")
    parser.add_argument("--fill", action="store_true", help="Fill URLs in database")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.scrape:
        sets = scrape_pricecharting_sets()
        if sets:
            MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(MAP_FILE, "w", encoding="utf-8") as f:
                json.dump(sets, f, indent=2, ensure_ascii=False)
            print(f"  Saved to {MAP_FILE}")

            # Show unmapped sets
            print("\n=== PriceCharting JP sets not in our mapping ===")
            for slug in sets.get("ja", []):
                if slug not in JP_SET_SLUGS.values():
                    print(f"  {slug}")

            print("\n=== PriceCharting CN sets not in our mapping ===")
            for slug in sets.get("zh-tw", []):
                if slug not in TW_SET_SLUGS.values():
                    print(f"  {slug}")

    if args.fill or not args.scrape:
        conn = ensure_schema()
        print("\n=== Filling PriceCharting URLs ===")
        filled, total = fill_pricecharting_urls(conn, args.dry_run)

        # Show coverage gaps
        print("\n=== Coverage gaps ===")
        for lang, label in [("en", "EN"), ("ja", "JP"), ("zh-tw", "TW")]:
            missing = total[lang] - filled[lang]
            if missing > 0:
                # Group by set
                unmapped = conn.execute("""
                    SELECT set_id, COUNT(*) as cnt
                    FROM cards WHERE language = ? AND (pricecharting_url IS NULL OR pricecharting_url = '')
                    GROUP BY set_id ORDER BY cnt DESC LIMIT 15
                """, (lang,)).fetchall()
                print(f"  {label} ({missing} missing):")
                for r in unmapped:
                    slug_map = EN_SET_SLUGS if lang == "en" else (JP_SET_SLUGS if lang == "ja" else TW_SET_SLUGS)
                    mapped = "MAPPED" if r["set_id"] in slug_map else "NOT MAPPED"
                    print(f"    {r['set_id']:15s}: {r['cnt']:4d} cards  [{mapped}]")

        conn.close()


if __name__ == "__main__":
    main()
