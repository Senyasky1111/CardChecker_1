"""
Match scraped CardMarket products to cards in our database.

Reads _cm_products_all.json (from scrape_cm_all_products.py) and matches
products to cards in cards.db by name + collector number + expansion, then
updates cm_id_product for each matched card.

Matching strategy (in priority order):
1. Build set_code → DB set_id mapping from CM product names
2. Build expansion_slug → set_id mapping from already-matched products
3. For each product: parse name + collector_number + set_code from CM name
4. Strategy A: Match by (name + number + set_id) — highest confidence
5. Strategy B: Match by (name + number) across sets — high confidence
6. Strategy C: Match by (name + set_id) if unique — medium confidence
7. Strategy D: Match by (name) if globally unique — low confidence

Key improvements over v1:
- HTML entity decoding (fixes &amp; → &, etc.)
- Number regex handles 1-4 digits (was 3-4, missed JP numbers like "46")
- Direct set_code matching from CM names to DB set_ids
- Trailing letter removal for split sets (DP4d/DP4m → DP4)
- x-prefix handling for JP Additionals (xsv2a → SV2a)
- Iterative matching: run multiple passes to build up expansion mapping

Usage:
    python scripts/match_cm_products.py              # Dry run (show matches)
    python scripts/match_cm_products.py --apply       # Apply changes to DB
    python scripts/match_cm_products.py --apply --iterations 5
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

DATA_DIR = Path("./data/cardmarket")
PRODUCTS_FILE = DATA_DIR / "_cm_products_all.json"
DB_PATH = Path("./data/cards.db")


def _normalize_name(name: str) -> str:
    """Normalize card name for matching."""
    # Decode HTML entities first
    name = html.unescape(name)
    # Remove ability/attack text in brackets
    name = re.sub(r"\s*\[.*?\]", "", name)
    # Remove parenthetical notes
    name = re.sub(r"\s*\(.*?\)", "", name)
    # Remove Lv. markers (e.g. "Lv.33", "Lv.X")
    name = re.sub(r"\s*Lv\.\s*\w+", "", name, flags=re.IGNORECASE)
    # Remove punctuation but keep alphanumeric + spaces
    name = re.sub(r"[^\w\s]", "", name)
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name)
    return name.strip().lower()


def _parse_cm_name(name: str) -> dict:
    """Parse a CardMarket display name to extract card name, set code, number.

    Handles formats like:
    - "Charizard ex  (SV2a 006)"  → name="Charizard ex", code="SV2a", number=6
    - "Roserade Lv.33  (DP1)"    → name="Roserade Lv.33", code="DP1", number=None
    - "Pikachu  (EXP)"           → name="Pikachu", code="EXP", number=None
    - "Feraligatr Lv.53  (DP2)"  → name="Feraligatr Lv.53", code="DP2", number=None
    """
    # Decode HTML entities
    name = html.unescape(name)
    result = {"name": name, "number": None, "set_code": ""}

    # Pattern 1: (SetCode Number) — e.g. (SV2a 006), (s5a 46), (IFDS 016)
    m = re.search(r'\(([A-Za-z0-9-]+)\s+(\d{1,4})\)', name)
    if m:
        result["set_code"] = m.group(1)
        result["number"] = int(m.group(2))
        result["name"] = name[:m.start()].strip()
        return result

    # Pattern 2: (SetCode) only — e.g. (DP1), (EXP), (G2)
    m = re.search(r'\(([A-Za-z0-9-]+)\)', name)
    if m:
        code = m.group(1)
        # Only treat as set code if it looks like one (not "Holo", "Reverse", etc.)
        if len(code) <= 8 and not code.lower() in (
            "holo", "reverse", "promo", "jumbo", "sealed", "booster",
            "display", "tin", "box", "pack", "foil", "reprint",
        ):
            result["set_code"] = code
            result["name"] = name[:m.start()].strip()
            return result

    # No parenthetical — clean up name
    result["name"] = re.sub(r'\s*\[.*?\]', '', name).strip()
    result["name"] = re.sub(r'\s*\(.*?\)', '', result["name"]).strip()
    return result


def _parse_slug(slug: str) -> dict:
    """Parse a CardMarket card slug to extract name and collector info."""
    card_slug = slug.split("/")[-1] if "/" in slug else slug
    result = {"raw": card_slug, "name": "", "number": None, "set_code": ""}

    # Pattern 1: -{SetCode}{Number} at end (e.g. "Pikachu-V1-MEW025")
    m = re.search(r'-([A-Z]{2,5})(\d{1,4})$', card_slug)
    if m:
        result["set_code"] = m.group(1)
        result["number"] = int(m.group(2))
        name_part = card_slug[:m.start()]
    else:
        # Pattern 2: -{SetCodeNumber} mixed (e.g. "Charizard-ex-s5a46")
        m = re.search(r'-([a-zA-Z][A-Za-z0-9-]*?)(\d{1,4})$', card_slug)
        if m:
            result["set_code"] = m.group(1)
            result["number"] = int(m.group(2))
            name_part = card_slug[:m.start()]
        else:
            name_part = card_slug

    # Remove version markers like V1, V2
    name_part = re.sub(r'-V\d+$', '', name_part)
    name_part = re.sub(r'-V\d+-', '-', name_part)
    result["name"] = name_part.replace("-", " ").strip()
    return result


def _build_set_code_map(db_set_ids: set[str]) -> dict[str, list[str]]:
    """Build a mapping from CM set codes to DB set_ids.

    Handles:
    - Exact match (case-insensitive): "SV2a" → "SV2a"
    - Trailing letter removal for split sets: "DP4d" → "DP4"
    - x-prefix for JP Additionals: "xsv2a" → "SV2a"
    """
    # Build case-insensitive lookup
    lower_to_real = defaultdict(list)
    for sid in db_set_ids:
        lower_to_real[sid.lower()].append(sid)

    code_to_sets: dict[str, list[str]] = {}

    def _register(code: str, db_sid: str):
        key = code.lower()
        if key not in code_to_sets:
            code_to_sets[key] = []
        if db_sid not in code_to_sets[key]:
            code_to_sets[key].append(db_sid)

    # For every DB set_id, register it directly
    for sid in db_set_ids:
        _register(sid, sid)

    # Also register common transformations that products might use
    # e.g., DP4d → DP4, BW1w → bw1, sm12a → sm12
    for sid in db_set_ids:
        sid_lower = sid.lower()
        # If set_id matches "{letters}{digits}", also register variants
        # with trailing letters: DP4 ← DP4d, DP4m, DP4p, etc.
        m = re.match(r'^([a-z]+\d+)$', sid_lower)
        if m:
            # This set can receive products with trailing letter codes
            pass  # Handled dynamically in _resolve_set_code

    return code_to_sets


def _resolve_set_code(code: str, db_set_ids: set[str],
                      lower_to_real: dict[str, list[str]]) -> list[str]:
    """Resolve a CM set code to DB set_id(s).

    Returns list of possible DB set_ids.
    """
    # Manual mappings for codes that can't be resolved automatically
    MANUAL_MAP: dict[str, list[str]] = {
        # JP Additionals (x-prefix codes that don't match DB set_ids)
        "xblk": ["SV11B"],     # Black Bolt Additionals → JP SV11B
        "xwht": ["SV11W"],     # White Flare Additionals → JP SV11W
        # Chinese/TW 151 collection
        "151c": ["SV2a"],      # Collect-151 → JP/TW SV2a
        # SV11 combined
        "sv11s": ["SV11B", "SV11W"],  # Black-White IDTH extras
        # JP DP-era variants with non-standard suffixes
        "dp4d": ["DP4"],       # Dawn Dash → DP4
        "dp4m": ["DP4"],       # Moonlit Pursuit → DP4
        "dp5t": ["DP5"],       # Temple of Anger → DP5
        "dp5c": ["DP5"],       # Cry from the Mysterious → DP5
        "dp3d": ["DP3"],       # Dialga deck → DP3
        "dp3p": ["DP3"],       # Palkia deck → DP3
        # TW set codes: strip leading C and trailing C → SV/S set
        "csv7c": ["SV7"],
        "csv6c": ["SV6"],
        "csv5c": ["SV5K", "SV5M"],
        "csv4c": ["SV4K", "SV4M"],
        "csv3c": ["SV3"],
        "csv1c": ["SV1S", "SV1V"],
        # Promos
        "dppr": ["DPP"],       # DP Black Star Promos → JP DPP
        "xypr": ["XYP"],       # XY Black Star Promos → JP XYP
        "swsh": ["SV-P"],      # SWSH Promos (partial)
    }

    if not code:
        return []

    code_lower = code.lower()

    # 0. Check manual mappings first
    if code_lower in MANUAL_MAP:
        result = []
        for sid in MANUAL_MAP[code_lower]:
            if sid in db_set_ids:
                result.append(sid)
            # Also check tw- version
            tw_sid = "tw-" + sid
            if tw_sid in db_set_ids:
                result.append(tw_sid)
        if result:
            return result

    # 1. Direct match (case-insensitive)
    if code_lower in lower_to_real:
        return lower_to_real[code_lower]

    # 2. x-prefix (JP Additionals): xsv2a → sv2a
    if code_lower.startswith("x") and len(code_lower) > 1:
        stripped = code_lower[1:]
        if stripped in lower_to_real:
            return lower_to_real[stripped]

    # 3. Trailing letter removal for split sets: DP4d → DP4
    m = re.match(r'^([a-z]+\d+)[a-z]$', code_lower)
    if m:
        parent = m.group(1)
        if parent in lower_to_real:
            return lower_to_real[parent]

    # 4. tw- prefix for TW: try adding tw-
    tw_key = "tw-" + code_lower
    if tw_key in lower_to_real:
        return lower_to_real[tw_key]

    return []


def load_scraped_products() -> dict[str, dict]:
    """Load scraped products from JSON."""
    if not PRODUCTS_FILE.exists():
        print(f"ERROR: {PRODUCTS_FILE} not found. Run scrape_cm_all_products.py first.")
        return {}

    with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    products = data.get("products", {})
    print(f"Loaded {len(products)} scraped products from "
          f"{len(data.get('scraped_expansions', []))} expansions")
    return products


def build_expansion_mapping(conn: sqlite3.Connection,
                            products: dict[str, dict]) -> dict[str, set[tuple[str, str]]]:
    """Build expansion_slug -> set of (set_id, language) mapping.

    Uses already-matched products to determine which CM expansion slug
    corresponds to which DB set_id.
    """
    exp_to_sets: dict[str, dict[tuple[str, str], int]] = defaultdict(
        lambda: defaultdict(int)
    )

    rows = conn.execute(
        "SELECT cm_id_product, set_id, language FROM cards "
        "WHERE cm_id_product IS NOT NULL"
    ).fetchall()

    for row in rows:
        pid = str(row[0])
        if pid in products:
            exp = products[pid].get("expansion", "")
            if exp:
                exp_to_sets[exp][(row[1], row[2])] += 1

    # For each expansion, keep sets with significant match count
    result: dict[str, set[tuple[str, str]]] = {}
    for exp, sets_counts in exp_to_sets.items():
        total = sum(sets_counts.values())
        filtered = set()
        for (set_id, lang), cnt in sets_counts.items():
            # Keep if has at least 2 matches or represents >5% of total
            if cnt >= 2 or cnt / total > 0.05:
                filtered.add((set_id, lang))
        if filtered:
            result[exp] = filtered

    print(f"Expansion mapping: {len(result)} CM expansions -> DB sets")
    return result


def build_db_index(conn: sqlite3.Connection) -> dict:
    """Build lookup indexes for matching.

    Returns dict with:
        by_set_name_number: {(set_id, lang, norm_name, number): [card, ...]}
        by_name_number: {(norm_name, number): [card, ...]}
        by_set_name: {(set_id, lang, norm_name): [card, ...]}
        by_name: {norm_name: [card, ...]}
        all_set_ids: set of all set_ids
        lower_to_real: {lower(set_id): [set_id, ...]}
    """
    rows = conn.execute("""
        SELECT c.tcgdex_id, c.name, c.eng_name, c.language, c.set_id,
               c.collector_number, c.cm_id_product,
               s.cm_expansion_id, s.name as set_name
        FROM cards c
        JOIN sets s ON c.set_id = s.set_id AND s.language = c.language
    """).fetchall()

    by_set_name_number = defaultdict(list)
    by_name_number = defaultdict(list)
    by_set_name = defaultdict(list)
    by_name = defaultdict(list)
    all_set_ids = set()
    lower_to_real = defaultdict(list)
    set_langs = set()  # {(set_id, language)} — which sets have cards in which langs

    for row in rows:
        card = dict(row)
        lang = card["language"]
        match_name = card["eng_name"] if lang in ("ja", "zh-tw") else card["name"]
        if not match_name:
            match_name = card["name"]

        norm = _normalize_name(match_name)
        number = card["collector_number"]
        set_id = card["set_id"]
        all_set_ids.add(set_id)
        set_langs.add((set_id, lang))

        if norm and number is not None:
            by_set_name_number[(set_id, lang, norm, number)].append(card)
            by_name_number[(norm, number)].append(card)
        if norm:
            by_set_name[(set_id, lang, norm)].append(card)
            by_name[norm].append(card)

    # Build lower_to_real mapping
    for sid in all_set_ids:
        key = sid.lower()
        if sid not in lower_to_real[key]:
            lower_to_real[key].append(sid)

    print(f"DB index: {len(by_set_name_number)} (set+name+number), "
          f"{len(by_name_number)} (name+number), "
          f"{len(by_name)} (name), "
          f"{len(all_set_ids)} sets")
    return {
        "by_set_name_number": by_set_name_number,
        "by_name_number": by_name_number,
        "by_set_name": by_set_name,
        "by_name": by_name,
        "all_set_ids": all_set_ids,
        "lower_to_real": dict(lower_to_real),
        "set_langs": set_langs,
    }


def _pick_best(candidates: list[dict]) -> dict:
    """Pick best candidate, preferring cards without cm_id_product."""
    for c in candidates:
        if c["cm_id_product"] is None:
            return c
    return candidates[0]


def match_products(products: dict[str, dict], db_index: dict,
                   exp_mapping: dict[str, set]) -> tuple[list[dict], list[dict]]:
    """Match scraped products to DB cards using expansion-aware matching."""
    matches = []
    unmatched = []
    stats = defaultdict(int)

    by_set_name_number = db_index["by_set_name_number"]
    by_name_number = db_index["by_name_number"]
    by_set_name = db_index["by_set_name"]
    by_name = db_index["by_name"]
    all_set_ids = db_index["all_set_ids"]
    lower_to_real = db_index["lower_to_real"]
    set_langs = db_index["set_langs"]

    for pid, prod in products.items():
        id_product = int(pid)
        cm_name = prod.get("name", "")
        cm_slug = prod.get("slug", "")
        cm_expansion = prod.get("expansion", "")

        # Parse name and slug
        parsed_name = _parse_cm_name(cm_name) if cm_name else {
            "name": "", "number": None, "set_code": ""
        }
        parsed_slug = _parse_slug(cm_slug)

        card_name = parsed_name["name"] or parsed_slug["name"]
        card_number = parsed_name.get("number") or parsed_slug.get("number")
        set_code = parsed_name.get("set_code") or parsed_slug.get("set_code", "")
        norm_name = _normalize_name(card_name)

        if not norm_name:
            continue

        # Get possible set_ids from TWO sources:
        # 1. Direct set_code resolution from product name
        # 2. Expansion slug mapping from already-matched products
        possible_sets_from_code = set()
        if set_code:
            resolved = _resolve_set_code(set_code, all_set_ids, lower_to_real)
            for sid in resolved:
                # Add ALL languages where this set has cards
                # (don't verify card name — let matching strategies handle it)
                for lang in ("en", "ja", "zh-tw"):
                    if (sid, lang) in set_langs:
                        possible_sets_from_code.add((sid, lang))

        possible_sets_from_exp = exp_mapping.get(cm_expansion, set())

        # Combine both sources
        possible_sets = possible_sets_from_code | possible_sets_from_exp

        matched_cards = []  # collect ALL matching cards (multi-lang)

        # Strategy A: name + number + set (highest confidence)
        # Try ALL possible sets (not just first) to match JP+TW+EN
        if card_number is not None and possible_sets:
            for set_id, lang in possible_sets:
                candidates = by_set_name_number.get(
                    (set_id, lang, norm_name, card_number), []
                )
                if candidates:
                    best = _pick_best(candidates)
                    matched_cards.append({
                        "id_product": id_product,
                        "tcgdex_id": best["tcgdex_id"],
                        "cm_name": card_name,
                        "db_name": best["name"],
                        "language": best["language"],
                        "number": card_number,
                        "confidence": "highest",
                        "already_has_cm_id": best["cm_id_product"] is not None,
                    })
                    stats["highest"] += 1

        # Strategy B: name + number across all sets
        if not matched_cards and card_number is not None:
            candidates = by_name_number.get((norm_name, card_number), [])
            if len(candidates) == 1:
                best = candidates[0]
                matched_cards.append({
                    "id_product": id_product,
                    "tcgdex_id": best["tcgdex_id"],
                    "cm_name": card_name,
                    "db_name": best["name"],
                    "language": best["language"],
                    "number": card_number,
                    "confidence": "high",
                    "already_has_cm_id": best["cm_id_product"] is not None,
                })
                stats["high"] += 1
            elif len(candidates) > 1 and possible_sets:
                # Multiple candidates -> match ALL that are in possible sets
                filtered = [c for c in candidates
                            if (c["set_id"], c["language"]) in possible_sets]
                for c in filtered:
                    best = c if c["cm_id_product"] is None else c
                    matched_cards.append({
                        "id_product": id_product,
                        "tcgdex_id": best["tcgdex_id"],
                        "cm_name": card_name,
                        "db_name": best["name"],
                        "language": best["language"],
                        "number": card_number,
                        "confidence": "high",
                        "already_has_cm_id": best["cm_id_product"] is not None,
                    })
                    stats["high_filtered"] += 1

        # Strategy C: name + set (if unique within set)
        # Try ALL possible sets
        if not matched_cards and possible_sets:
            for set_id, lang in possible_sets:
                candidates = by_set_name.get((set_id, lang, norm_name), [])
                if len(candidates) == 1:
                    best = candidates[0]
                    matched_cards.append({
                        "id_product": id_product,
                        "tcgdex_id": best["tcgdex_id"],
                        "cm_name": card_name,
                        "db_name": best["name"],
                        "language": best["language"],
                        "number": card_number,
                        "confidence": "medium",
                        "already_has_cm_id": best["cm_id_product"] is not None,
                    })
                    stats["medium"] += 1

        # Strategy C2: name + set, multiple candidates but only ONE without cm_id
        # Handles art variants (V1, V2, V3) — CM products get assigned one-by-one
        if not matched_cards and possible_sets:
            for set_id, lang in possible_sets:
                candidates = by_set_name.get((set_id, lang, norm_name), [])
                if len(candidates) > 1:
                    unmatched_cands = [c for c in candidates
                                       if c["cm_id_product"] is None]
                    if len(unmatched_cands) == 1:
                        best = unmatched_cands[0]
                        matched_cards.append({
                            "id_product": id_product,
                            "tcgdex_id": best["tcgdex_id"],
                            "cm_name": card_name,
                            "db_name": best["name"],
                            "language": best["language"],
                            "number": card_number,
                            "confidence": "medium_last",
                            "already_has_cm_id": False,
                        })
                        stats["medium_last"] += 1
                        break

        # Strategy D: name only (if globally unique)
        if not matched_cards:
            candidates = by_name.get(norm_name, [])
            if len(candidates) == 1:
                best = candidates[0]
                matched_cards.append({
                    "id_product": id_product,
                    "tcgdex_id": best["tcgdex_id"],
                    "cm_name": card_name,
                    "db_name": best["name"],
                    "language": best["language"],
                    "number": card_number,
                    "confidence": "low",
                    "already_has_cm_id": best["cm_id_product"] is not None,
                })
                stats["low"] += 1

        if matched_cards:
            matches.extend(matched_cards)
        else:
            unmatched.append({
                "id_product": id_product,
                "name": card_name,
                "slug": cm_slug,
                "expansion": cm_expansion,
                "set_code": set_code,
                "candidates": len(by_name.get(norm_name, [])),
                "has_set_mapping": bool(possible_sets),
            })

    print(f"\nMatch strategy breakdown:")
    for strategy, cnt in sorted(stats.items()):
        print(f"  {strategy}: {cnt}")

    return matches, unmatched


def apply_matches(conn: sqlite3.Connection, matches: list[dict]) -> dict:
    """Apply matches to the database. Returns stats."""
    stats = {"updated": 0, "skipped_existing": 0, "by_language": defaultdict(int)}

    for m in matches:
        if m["already_has_cm_id"]:
            stats["skipped_existing"] += 1
            continue

        conn.execute(
            "UPDATE cards SET cm_id_product = ? WHERE tcgdex_id = ?",
            (m["id_product"], m["tcgdex_id"]),
        )
        stats["updated"] += 1
        stats["by_language"][m["language"]] += 1

    conn.commit()
    return stats


def main():
    parser = argparse.ArgumentParser(description="Match CM products to DB cards")
    parser.add_argument("--apply", action="store_true",
                        help="Apply changes to database (default: dry run)")
    parser.add_argument("--iterations", type=int, default=5,
                        help="Number of iterative matching passes (default: 5)")
    args = parser.parse_args()

    # Load scraped products
    products = load_scraped_products()
    if not products:
        return

    # Build DB index
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    total_new = 0

    for iteration in range(1, args.iterations + 1):
        print(f"\n{'='*60}")
        print(f"=== Iteration {iteration}/{args.iterations} ===")
        print(f"{'='*60}")

        # Rebuild DB index (picks up new cm_id_product from previous iteration)
        db_index = build_db_index(conn)

        # Rebuild expansion mapping
        exp_mapping = build_expansion_mapping(conn, products)

        # Match
        matches, unmatched = match_products(products, db_index, exp_mapping)

        # Stats
        new_matches = [m for m in matches if not m["already_has_cm_id"]]

        print(f"\n=== Iteration {iteration} Results ===")
        print(f"Total matches: {len(matches)}")
        conf_counts = defaultdict(int)
        for m in matches:
            conf_counts[m["confidence"]] += 1
        for conf in ("highest", "high", "high_filtered", "medium", "low"):
            if conf_counts.get(conf, 0) > 0:
                print(f"  {conf}: {conf_counts[conf]}")
        print(f"  Already have cm_id_product: "
              f"{sum(1 for m in matches if m['already_has_cm_id'])}")
        print(f"  NEW matches (no cm_id yet): {len(new_matches)}")
        print(f"Unmatched products: {len(unmatched)}")

        if not new_matches:
            print(f"\nNo new matches found. Stopping iterations.")
            break

        total_new += len(new_matches)

        if args.apply:
            print(f"\n--- Applying {len(new_matches)} new matches ---")
            stats = apply_matches(conn, matches)
            print(f"Updated: {stats['updated']}")
            for lang, cnt in sorted(stats["by_language"].items()):
                print(f"  {lang}: {cnt}")
        else:
            print(f"\n[DRY RUN] Would apply {len(new_matches)} new matches")
            # In dry run, no point iterating since DB won't change
            break

    # Final stats
    print(f"\n{'='*60}")
    print(f"=== FINAL RESULTS ===")
    print(f"{'='*60}")
    print(f"Total new matches applied: {total_new}")

    for lang in ("en", "ja", "zh-tw"):
        total = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE language=?", (lang,)
        ).fetchone()[0]
        with_cm = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE language=? AND cm_id_product IS NOT NULL",
            (lang,)
        ).fetchone()[0]
        print(f"{lang}: {with_cm}/{total} have cm_id_product ({100*with_cm/total:.1f}%)")

    # Unmatched analysis
    if unmatched:
        exp_counts = defaultdict(int)
        for u in unmatched:
            exp_counts[u["expansion"]] += 1
        print(f"\nTop 15 unmatched expansions:")
        for exp, cnt in sorted(exp_counts.items(), key=lambda x: -x[1])[:15]:
            print(f"  {exp}: {cnt}")

    if not args.apply and total_new == 0 and new_matches:
        print(f"\n[DRY RUN] Use --apply to update the database")

    conn.close()


if __name__ == "__main__":
    main()
