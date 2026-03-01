"""Fill missing eng_name for JP/TW cards using Gemini AI translation.

Many JP/TW Trainer/Supporter/Item/Stadium cards have localized character names
that don't match their EN equivalents (e.g. サカキ → Giovanni, アテナ → Ariana).
This script uses Gemini to translate these names to their official EN Pokemon TCG names.

Usage:
    python scripts/fill_eng_names_gemini.py [--dry-run] [--lang ja|zh-tw|all]
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

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import GEMINI_API_KEY
from src.db import ensure_schema

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("ERROR: google-genai not installed. Run: pip install google-genai")
    sys.exit(1)


BATCH_SIZE = 50  # names per Gemini request
CACHE_FILE = Path("data/eng_name_translations.json")


def _load_cache() -> dict[str, str]:
    """Load previously translated names from cache."""
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict[str, str]):
    """Save translations to cache file."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def _translate_batch_gemini(names: list[str], lang: str, client) -> dict[str, str]:
    """Translate a batch of card names using Gemini.

    Args:
        names: List of JP/TW card names to translate.
        lang: Source language ('ja' or 'zh-tw').
        client: Gemini client instance.

    Returns:
        Dict mapping original name -> English translation.
    """
    lang_label = "Japanese" if lang == "ja" else "Traditional Chinese (Taiwan)"

    # Build numbered list for structured output
    name_list = "\n".join(f"{i+1}. {name}" for i, name in enumerate(names))

    prompt = f"""You are a Pokemon TCG expert. Translate these {lang_label} Pokemon Trading Card Game card names to their OFFICIAL English names as used in the English Pokemon TCG releases.

IMPORTANT RULES:
- Use the OFFICIAL English TCG card name, not a literal translation
- For character names, use the official English localization (e.g. サカキ = Giovanni, not Sakaki)
- For Trainer/Supporter cards with character names, the English name uses the English character name (e.g. ロケット団のサカキ = Team Rocket's Giovanni)
- For Item/Tool/Stadium cards, use the official English card name
- For Energy cards, use the official English name
- If you're not sure of the exact official name, provide your best translation
- Keep the same numbering in your response

Card names to translate:
{name_list}

Respond with ONLY the numbered translations, one per line, in the format:
1. English Name
2. English Name
...
"""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            text = response.text.strip()

            # Parse numbered responses
            result = {}
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Match "1. Name" or "1) Name" patterns
                m = re.match(r"^(\d+)[.)]\s*(.+)$", line)
                if m:
                    idx = int(m.group(1)) - 1
                    eng_name = m.group(2).strip()
                    if 0 <= idx < len(names):
                        result[names[idx]] = eng_name

            return result
        except Exception as e:
            error_str = str(e)
            if "429" in error_str and attempt < max_retries - 1:
                # Extract retry delay from error message
                delay_match = re.search(r"retry in ([\d.]+)s", error_str)
                wait = float(delay_match.group(1)) + 2 if delay_match else 30
                print(f"rate limited, waiting {wait:.0f}s...", end=" ", flush=True)
                time.sleep(wait)
            else:
                print(f"  Gemini error: {e}")
                return {}


def get_missing_names(conn, lang: str) -> list[str]:
    """Get all unique card names without eng_name for a language."""
    rows = conn.execute("""
        SELECT DISTINCT name FROM cards
        WHERE language = ? AND (eng_name IS NULL OR eng_name = '')
        ORDER BY name
    """, (lang,)).fetchall()
    return [r["name"] for r in rows]


def fill_eng_names(conn, lang: str, translations: dict[str, str], dry_run: bool = False) -> int:
    """Apply translations to the database."""
    filled = 0
    for jp_name, eng_name in translations.items():
        if not eng_name:
            continue
        cards = conn.execute("""
            SELECT tcgdex_id FROM cards
            WHERE language = ? AND name = ? AND (eng_name IS NULL OR eng_name = '')
        """, (lang, jp_name)).fetchall()

        for card in cards:
            if not dry_run:
                conn.execute(
                    "UPDATE cards SET eng_name = ? WHERE tcgdex_id = ?",
                    (eng_name, card["tcgdex_id"])
                )
            filled += 1

    if not dry_run:
        conn.commit()
    return filled


def cross_fill_jp_tw(conn, dry_run: bool = False) -> int:
    """After filling JP eng_names, try to fill TW cards that have the same eng_name candidates.

    Strategy: Find TW cards without eng_name whose name matches a JP card
    that now HAS eng_name (via shared card identity across JP/TW).
    """
    # This won't work directly since JP and TW have different names.
    # Instead, try matching TW cards to JP cards within the same set by collector number.
    filled = 0

    tw_missing = conn.execute("""
        SELECT tcgdex_id, name, set_id, collector_number FROM cards
        WHERE language = 'zh-tw' AND (eng_name IS NULL OR eng_name = '')
    """).fetchall()

    for tw_card in tw_missing:
        tw_set = tw_card["set_id"]
        tw_num = tw_card["collector_number"]

        # Convert tw-SV10 -> SV10 for JP lookup
        jp_set = re.sub(r"^tw-", "", tw_set)

        # Find JP card in same set with same collector number
        jp_card = conn.execute("""
            SELECT eng_name FROM cards
            WHERE language = 'ja' AND set_id = ? AND collector_number = ?
            AND eng_name IS NOT NULL AND eng_name != ''
            LIMIT 1
        """, (jp_set, tw_num)).fetchone()

        if jp_card:
            if not dry_run:
                conn.execute(
                    "UPDATE cards SET eng_name = ? WHERE tcgdex_id = ?",
                    (jp_card["eng_name"], tw_card["tcgdex_id"])
                )
            filled += 1

    if not dry_run:
        conn.commit()
    return filled


def main():
    parser = argparse.ArgumentParser(description="Fill missing eng_name using Gemini translation")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    parser.add_argument("--lang", choices=["ja", "zh-tw", "all"], default="all",
                        help="Language to process (default: all)")
    args = parser.parse_args()

    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not set in .env")
        sys.exit(1)

    # Configure Gemini client (new SDK)
    client = genai.Client(api_key=GEMINI_API_KEY)

    conn = ensure_schema()
    cache = _load_cache()

    langs = ["ja", "zh-tw"] if args.lang == "all" else [args.lang]

    for lang in langs:
        label = "JP" if lang == "ja" else "TW"
        print(f"\n{'='*50}")
        print(f"Processing {label} cards")
        print(f"{'='*50}")

        # Get unique names that need translation
        missing_names = get_missing_names(conn, lang)
        print(f"  Unique names without eng_name: {len(missing_names)}")

        # Filter out already cached translations
        cache_key_prefix = f"{lang}:"
        to_translate = []
        cached_translations = {}
        for name in missing_names:
            cache_key = f"{cache_key_prefix}{name}"
            if cache_key in cache:
                cached_translations[name] = cache[cache_key]
            else:
                to_translate.append(name)

        print(f"  Already cached: {len(cached_translations)}")
        print(f"  Need translation: {len(to_translate)}")

        # Translate in batches
        new_translations = {}
        if to_translate:
            num_batches = (len(to_translate) + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"  Translating in {num_batches} batches of {BATCH_SIZE}...")

            for i in range(0, len(to_translate), BATCH_SIZE):
                batch = to_translate[i:i + BATCH_SIZE]
                batch_num = i // BATCH_SIZE + 1
                print(f"  Batch {batch_num}/{num_batches} ({len(batch)} names)...", end=" ", flush=True)

                result = _translate_batch_gemini(batch, lang, client)
                new_translations.update(result)
                print(f"got {len(result)} translations")

                # Save to cache incrementally
                for name, eng in result.items():
                    cache[f"{cache_key_prefix}{name}"] = eng
                _save_cache(cache)

                # Rate limit
                if i + BATCH_SIZE < len(to_translate):
                    time.sleep(2)

        # Combine cached and new translations
        all_translations = {**cached_translations, **new_translations}
        print(f"\n  Total translations: {len(all_translations)}/{len(missing_names)}")

        # Report untranslated
        untranslated = set(missing_names) - set(all_translations.keys())
        if untranslated:
            print(f"  Untranslated: {len(untranslated)}")
            for name in sorted(untranslated)[:10]:
                print(f"    - {name}")

        # Show sample translations
        print(f"\n  Sample translations:")
        for name, eng in list(all_translations.items())[:15]:
            print(f"    {name} -> {eng}")

        # Apply to database
        if all_translations:
            filled = fill_eng_names(conn, lang, all_translations, args.dry_run)
            print(f"\n  {'Would fill' if args.dry_run else 'Filled'}: {filled} cards")

    # Cross-fill: after JP is done, try to fill TW from JP by set+number
    if "zh-tw" in langs:
        print(f"\n{'='*50}")
        print(f"Cross-filling TW from JP (same set + collector number)")
        print(f"{'='*50}")
        cross_filled = cross_fill_jp_tw(conn, args.dry_run)
        print(f"  {'Would cross-fill' if args.dry_run else 'Cross-filled'}: {cross_filled} TW cards")

    # Final stats
    print(f"\n{'='*50}")
    print("Final eng_name coverage")
    print(f"{'='*50}")
    for lang_code, label in [("ja", "JP"), ("zh-tw", "TW"), ("en", "EN")]:
        total = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE language=?", (lang_code,)
        ).fetchone()[0]
        has_eng = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE language=? AND eng_name IS NOT NULL AND eng_name != ''",
            (lang_code,)
        ).fetchone()[0]
        missing = total - has_eng
        print(f"  {label}: {has_eng}/{total} ({100*has_eng/total:.1f}%) — missing: {missing}")

    conn.close()


if __name__ == "__main__":
    main()
