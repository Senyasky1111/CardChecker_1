"""
Enrich metadata.pkl with printed collector numbers from TCGdex API.

For each card in the FAISS index, adds:
  _printed_number    - int, the number printed on the card (e.g., 57)
  _printed_total     - int, total cards in the set (e.g., 191)
  _printed_set_code  - str, printed set abbreviation (e.g., "SSP")

Usage:
    py -3.11 scripts/enrich_metadata.py
    py -3.11 scripts/enrich_metadata.py --force-fetch   # Re-fetch from API
"""

from __future__ import annotations

import argparse
import json
import pickle
import re
import shutil
import time
from pathlib import Path

import requests

DATA_DIR = Path("./data/cardmarket")
INDEX_DIR = Path("./models/card_index")

METADATA_PATH = INDEX_DIR / "metadata.pkl"
SETS_CACHE_PATH = DATA_DIR / "_tcgdex_sets_cache.json"
ABBREVS_PATH = DATA_DIR / "_set_abbreviations.json"

TCGDEX_API = "https://api.tcgdex.net/v2/en"
REQUEST_DELAY = 0.3  # seconds between API calls


# ------------------------------------------------------------------
# Step 1: Fetch set data from TCGdex API
# ------------------------------------------------------------------

def fetch_all_sets(set_ids: list[str], force: bool = False) -> dict[str, dict]:
    """
    Fetch set details from TCGdex API for each set_id.

    Returns {set_id: {abbreviation, official_count, name}}.
    Caches to _tcgdex_sets_cache.json to avoid re-fetching.
    """
    # Load existing cache
    cache: dict[str, dict] = {}
    if SETS_CACHE_PATH.exists() and not force:
        with open(SETS_CACHE_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)

    to_fetch = [s for s in set_ids if s not in cache]
    if not to_fetch:
        print(f"All {len(set_ids)} sets already cached.")
        return cache

    print(f"Fetching {len(to_fetch)} sets from TCGdex API...")
    fetched = 0
    errors = 0

    for i, set_id in enumerate(to_fetch):
        url = f"{TCGDEX_API}/sets/{set_id}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()

                # Extract abbreviation — can be a string or a dict with .official
                abbr_raw = data.get("abbreviation", "")
                if isinstance(abbr_raw, dict):
                    abbreviation = abbr_raw.get("official", "") or ""
                else:
                    abbreviation = str(abbr_raw) if abbr_raw else ""

                # Extract card count
                card_count = data.get("cardCount", {})
                if isinstance(card_count, dict):
                    official_count = card_count.get("official", 0) or 0
                else:
                    official_count = 0

                cache[set_id] = {
                    "abbreviation": abbreviation,
                    "official_count": official_count,
                    "name": data.get("name", ""),
                }
                fetched += 1
            elif resp.status_code == 404:
                # Set not found in API — store empty
                cache[set_id] = {
                    "abbreviation": "",
                    "official_count": 0,
                    "name": "",
                }
                fetched += 1
            else:
                print(f"  [{resp.status_code}] {set_id}")
                errors += 1
        except Exception as e:
            print(f"  Error fetching {set_id}: {e}")
            errors += 1

        # Progress
        if (i + 1) % 20 == 0:
            print(f"  ... {i + 1}/{len(to_fetch)} sets fetched")

        time.sleep(REQUEST_DELAY)

    # Save cache
    with open(SETS_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

    print(f"Fetched {fetched} sets ({errors} errors). Cache: {len(cache)} total.")
    return cache


# ------------------------------------------------------------------
# Step 2: Update set abbreviations
# ------------------------------------------------------------------

def update_set_abbreviations(sets_data: dict[str, dict]) -> dict[str, str]:
    """
    Merge API data into _set_abbreviations.json.

    Returns {set_id: abbreviation}.
    """
    # Load existing
    existing: dict[str, str] = {}
    if ABBREVS_PATH.exists():
        with open(ABBREVS_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)

    updated = 0
    for set_id, info in sets_data.items():
        api_abbr = info.get("abbreviation", "")
        current = existing.get(set_id, "")

        # Update if API has data and current is empty or different
        if api_abbr and (not current or current != api_abbr):
            existing[set_id] = api_abbr
            updated += 1
        elif set_id not in existing:
            existing[set_id] = api_abbr
            updated += 1

    # Save
    with open(ABBREVS_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False, sort_keys=True)

    print(f"Set abbreviations: {len(existing)} entries ({updated} updated).")
    return existing


# ------------------------------------------------------------------
# Step 3: Enrich metadata.pkl
# ------------------------------------------------------------------

# Regex to extract trailing digits from localId (handles "HGSS01", "TK1O", etc.)
_TRAILING_DIGITS = re.compile(r"(\d+)$")


def enrich_metadata(sets_data: dict[str, dict]) -> None:
    """
    Load metadata.pkl, add _printed_number, _printed_total, _printed_set_code
    to every card entry, save back.
    """
    if not METADATA_PATH.exists():
        print(f"ERROR: {METADATA_PATH} not found.")
        return

    # Backup
    backup_path = METADATA_PATH.with_suffix(".pkl.bak")
    if not backup_path.exists():
        shutil.copy2(METADATA_PATH, backup_path)
        print(f"Backup: {backup_path}")

    # Load
    with open(METADATA_PATH, "rb") as f:
        meta = pickle.load(f)

    cards_by_idx = meta.get("cards_by_idx", {})
    cards_by_id = meta.get("cards_by_id", {})

    enriched = 0
    skipped = 0
    no_tcgdex = 0

    for idx, card in cards_by_idx.items():
        tcgdex_id = card.get("_tcgdex_id", "")
        if not tcgdex_id or "-" not in tcgdex_id:
            no_tcgdex += 1
            continue

        parts = tcgdex_id.rsplit("-", 1)
        set_id = parts[0]
        local_part = parts[1]

        # Parse number from localId
        m = _TRAILING_DIGITS.search(local_part)
        if m:
            printed_number = int(m.group(1))
        else:
            skipped += 1
            continue

        # Get set info
        set_info = sets_data.get(set_id, {})
        printed_total = set_info.get("official_count", 0) or 0
        printed_set_code = set_info.get("abbreviation", "") or ""

        # Enrich
        card["_printed_number"] = printed_number
        card["_printed_total"] = printed_total
        card["_printed_set_code"] = printed_set_code
        enriched += 1

    # Also update cards_by_id (same objects may be shared, but be safe)
    for pid, card in cards_by_id.items():
        tcgdex_id = card.get("_tcgdex_id", "")
        if not tcgdex_id or "-" not in tcgdex_id:
            continue
        parts = tcgdex_id.rsplit("-", 1)
        set_id = parts[0]
        local_part = parts[1]
        m = _TRAILING_DIGITS.search(local_part)
        if not m:
            continue
        set_info = sets_data.get(set_id, {})
        card["_printed_number"] = int(m.group(1))
        card["_printed_total"] = set_info.get("official_count", 0) or 0
        card["_printed_set_code"] = set_info.get("abbreviation", "") or ""

    # Save
    with open(METADATA_PATH, "wb") as f:
        pickle.dump(meta, f)

    print(f"Enriched {enriched} of {len(cards_by_idx)} entries "
          f"({skipped} unparseable, {no_tcgdex} no tcgdex_id).")

    # Show some samples
    print("\nSamples:")
    for idx in [0, 100, 500, 1000]:
        c = cards_by_idx.get(idx, {})
        if c:
            print(f"  [{idx}] {c.get('name', '?')[:40]:40s} "
                  f"#{c.get('_printed_number', '?')}/{c.get('_printed_total', '?')} "
                  f"[{c.get('_printed_set_code', '?')}] "
                  f"(tcgdex={c.get('_tcgdex_id', '?')})")


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Enrich metadata with printed collector numbers")
    parser.add_argument("--force-fetch", action="store_true",
                        help="Re-fetch all sets from TCGdex API (ignore cache)")
    args = parser.parse_args()

    print("=" * 60)
    print("Enriching Card Metadata with TCGdex Set Data")
    print("=" * 60)

    # Step 1: Get all unique set IDs from metadata
    with open(METADATA_PATH, "rb") as f:
        meta = pickle.load(f)

    set_ids = set()
    for c in meta["cards_by_idx"].values():
        tid = c.get("_tcgdex_id", "")
        if tid and "-" in tid:
            set_ids.add(tid.rsplit("-", 1)[0])
    print(f"Found {len(set_ids)} unique set IDs in metadata.\n")

    # Step 2: Fetch set details
    sets_data = fetch_all_sets(sorted(set_ids), force=args.force_fetch)

    # Step 3: Update abbreviations file
    update_set_abbreviations(sets_data)

    # Step 4: Enrich metadata
    print()
    enrich_metadata(sets_data)

    print("\nDone!")


if __name__ == "__main__":
    main()
