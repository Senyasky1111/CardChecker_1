"""
Build Pokemon name translation dictionary: JP/TW → English.

Uses PokeAPI to get official Pokemon species names in all languages.
Then updates the eng_name column in the cards database for JP and TW cards.

Usage:
    py -3.11 scripts/build_name_map.py                # build dict + update DB
    py -3.11 scripts/build_name_map.py --dict-only     # just build the dictionary file
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import ensure_schema

DICT_FILE = Path("data/pokemon_name_dict.json")
POKEAPI_URL = "https://pokeapi.co/api/v2/pokemon-species/{id}"
MAX_SPECIES_ID = 1025  # Through Gen IX

HEADERS = {"User-Agent": "PokemonCardRecognition/1.0"}


def build_name_dictionary() -> dict:
    """
    Fetch all Pokemon species names from PokeAPI.

    Returns dict: {
        "ja": {"ピカチュウ": "Pikachu", "ギャラドス": "Gyarados", ...},
        "ja_romaji": {"pikachuu": "Pikachu", ...},
        "zh-Hant": {"皮卡丘": "Pikachu", ...},
        "zh-Hans": {"皮卡丘": "Pikachu", ...},
    }
    """
    if DICT_FILE.exists():
        print(f"Loading existing dictionary from {DICT_FILE}")
        with open(DICT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    print(f"Fetching Pokemon species names from PokeAPI (1-{MAX_SPECIES_ID})...")
    session = requests.Session()
    session.headers.update(HEADERS)

    name_map = {"ja": {}, "ja_romaji": {}, "zh-Hant": {}, "zh-Hans": {}}
    errors = []

    for species_id in range(1, MAX_SPECIES_ID + 1):
        try:
            resp = session.get(POKEAPI_URL.format(id=species_id), timeout=10)
            if resp.status_code != 200:
                errors.append(species_id)
                continue

            data = resp.json()
            names = data.get("names", [])

            en_name = None
            ja_name = None
            ja_romaji_name = None
            zh_hant_name = None
            zh_hans_name = None

            for entry in names:
                lang = entry["language"]["name"]
                name = entry["name"]
                if lang == "en":
                    en_name = name
                elif lang == "ja":
                    ja_name = name
                elif lang in ("roomaji", "ja-roma"):
                    ja_romaji_name = name
                elif lang in ("zh-Hant", "zh-hant"):
                    zh_hant_name = name
                elif lang in ("zh-Hans", "zh-hans"):
                    zh_hans_name = name

            if en_name:
                if ja_name:
                    name_map["ja"][ja_name] = en_name
                if ja_romaji_name:
                    name_map["ja_romaji"][ja_romaji_name.lower()] = en_name
                if zh_hant_name:
                    name_map["zh-Hant"][zh_hant_name] = en_name
                if zh_hans_name:
                    name_map["zh-Hans"][zh_hans_name] = en_name

        except Exception as e:
            print(f"  Error for species {species_id}: {e}")
            errors.append(species_id)

        if species_id % 100 == 0:
            print(f"  Fetched {species_id}/{MAX_SPECIES_ID}")
            time.sleep(1)  # Rate limit

    # Save dictionary
    DICT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DICT_FILE, "w", encoding="utf-8") as f:
        json.dump(name_map, f, ensure_ascii=False, indent=2)

    print(f"\nDictionary built:")
    print(f"  JA names: {len(name_map['ja'])}")
    print(f"  ZH-Hant names: {len(name_map['zh-Hant'])}")
    print(f"  ZH-Hans names: {len(name_map['zh-Hans'])}")
    if errors:
        print(f"  Errors: {len(errors)} species")

    return name_map


def _find_pokemon_in_name(card_name: str, pokemon_dict: dict[str, str]) -> str:
    """
    Try to find a known Pokemon name within a card name.

    Handles compound names like:
    - "カスミのギャラドス" (Misty's Gyarados) → "Gyarados"
    - "ピカチュウex" → "Pikachu"
    - "ギャラドスex" → "Gyarados"

    Returns English name if found, empty string otherwise.
    """
    # Direct match
    if card_name in pokemon_dict:
        return pokemon_dict[card_name]

    # Strip common suffixes (ex, EX, GX, V, VMAX, VSTAR, etc.)
    stripped = re.sub(r"(ex|EX|GX|V|VMAX|VSTAR|BREAK|δ|☆|スター|ＥＸ)\s*$", "", card_name).strip()
    if stripped in pokemon_dict:
        en = pokemon_dict[stripped]
        # Preserve the suffix in English
        suffix = card_name[len(stripped):].strip()
        return f"{en} {suffix}".strip() if suffix else en

    # Check if any known Pokemon name is a substring (for compound names)
    # Sort by length descending to match longest first (e.g., "ピカチュウ" before "チュウ")
    for jp_name in sorted(pokemon_dict.keys(), key=len, reverse=True):
        if jp_name in card_name and len(jp_name) >= 2:
            return pokemon_dict[jp_name]

    return ""


def update_eng_names_in_db(name_map: dict) -> None:
    """Update eng_name column for JP and TW cards in the database."""
    conn = ensure_schema()

    # Get all JP and TW cards that don't have eng_name set
    rows = conn.execute(
        "SELECT tcgdex_id, name, language FROM cards WHERE language IN ('ja', 'zh-tw') AND (eng_name IS NULL OR eng_name = '')"
    ).fetchall()

    if not rows:
        print("No cards need eng_name update.")
        return

    print(f"Updating eng_name for {len(rows)} cards...")
    updated = 0

    for row in rows:
        card_id = row["tcgdex_id"]
        card_name = row["name"]
        lang = row["language"]

        if lang == "ja":
            eng_name = _find_pokemon_in_name(card_name, name_map.get("ja", {}))
        elif lang == "zh-tw":
            eng_name = _find_pokemon_in_name(card_name, name_map.get("zh-Hant", {}))
        else:
            continue

        if eng_name:
            conn.execute(
                "UPDATE cards SET eng_name = ? WHERE tcgdex_id = ?",
                (eng_name, card_id),
            )
            updated += 1

    conn.commit()
    print(f"Updated {updated}/{len(rows)} cards with English names.")

    # Also set eng_name = name for EN cards that don't have it
    conn.execute("UPDATE cards SET eng_name = name WHERE language = 'en' AND (eng_name IS NULL OR eng_name = '')")
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Build Pokemon name translation dictionary")
    parser.add_argument("--dict-only", action="store_true", help="Only build dictionary, don't update DB")
    args = parser.parse_args()

    name_map = build_name_dictionary()

    if not args.dict_only:
        update_eng_names_in_db(name_map)


if __name__ == "__main__":
    main()
