"""
Test 100 random cards: send DB images to /identify-v2, check recognition + URLs.

Picks 100 random card images from data/cardmarket/images/,
sends each to /identify-v2, and checks:
  1. Did the API return success?
  2. Does the top match correspond to the correct card (by filename)?
  3. Are cardmarket_url / tcgplayer_url / pricecharting_url present and valid?

Usage:
    # Start the server first:
    #   ./venv/Scripts/python.exe -m uvicorn src.api:app --host 0.0.0.0 --port 8000
    # Then run:
    ./venv/Scripts/python.exe scripts/test_100_cards.py
    ./venv/Scripts/python.exe scripts/test_100_cards.py --check-urls  # also HEAD-check CardMarket URLs
"""

import io
import json
import os
import random
import re
import sqlite3
import sys
import time
from pathlib import Path

# Fix encoding for Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests

API_BASE = "http://127.0.0.1:8000"
IMAGES_DIR = Path("data/cardmarket/images")
DB_PATH = Path("data/cards.db")
N_CARDS = 100

# Cache DB lookups
_db_cache = {}


def _get_db():
    """Get a SQLite connection (cached)."""
    if "conn" not in _db_cache:
        _db_cache["conn"] = sqlite3.connect(str(DB_PATH))
        _db_cache["conn"].row_factory = sqlite3.Row
    return _db_cache["conn"]


def parse_filename(path: Path):
    """Extract language, set_id, collector_number from filename.

    Filename patterns:
      en_sv06.5-051.jpg  -> tcgdex_id = sv06.5-051
      ja_A1-001.jpg      -> tcgdex_id = A1-001
      ja_jp-30542.jpg    -> tcgdex_id = jp-30542 (generic JP, real set in DB)
      zh-tw_S10a-999.jpg -> tcgdex_id = S10a-999
      zh-tw_tw-MC-725.jpg -> tcgdex_id = tw-MC-725 (generic TW)
      804750.jpg         -> cm_id_product (no lang prefix)
    """
    stem = path.stem

    # Pattern: lang_setid-number
    m = re.match(r"^(en|ja|zh-tw)_(.+)-(\d+)$", stem)
    if not m:
        return None

    lang = m.group(1)
    set_id = m.group(2)
    number = int(m.group(3))

    # Build tcgdex_id from filename parts
    tcgdex_id = f"{set_id}-{number}"

    # For generic JP/TW cards, look up real set_id from DB
    if set_id in ("jp", "tw-MC"):
        row = _get_db().execute(
            "SELECT set_id, collector_number FROM cards WHERE tcgdex_id = ?",
            (tcgdex_id,),
        ).fetchone()
        if row:
            set_id = row["set_id"]
            number = row["collector_number"] if row["collector_number"] is not None else number

    return {
        "language": lang,
        "set_id": set_id,
        "collector_number": number,
        "tcgdex_id": tcgdex_id,
    }


def pick_random_cards(n: int):
    """Pick n random card images from the images directory."""
    all_images = list(IMAGES_DIR.rglob("*.jpg"))
    if not all_images:
        print(f"ERROR: No images found in {IMAGES_DIR}")
        sys.exit(1)
    print(f"Found {len(all_images)} total images, picking {n}...")
    return random.sample(all_images, min(n, len(all_images)))


def check_url(url: str, timeout: float = 5.0) -> dict:
    """Check if a URL is reachable (HEAD request, follow redirects)."""
    if not url:
        return {"valid": False, "reason": "empty"}
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True)
        return {
            "valid": resp.status_code < 400,
            "status": resp.status_code,
            "final_url": str(resp.url),
        }
    except requests.RequestException as e:
        return {"valid": False, "reason": str(e)}


def test_card(image_path: Path, check_urls: bool = False):
    """Send a card image to /identify-v2 and evaluate the result."""
    expected = parse_filename(image_path)
    if not expected:
        return {"status": "skip", "reason": f"cannot parse filename: {image_path.name}"}

    with open(image_path, "rb") as f:
        img_bytes = f.read()

    start = time.time()
    try:
        resp = requests.post(
            f"{API_BASE}/identify-v2",
            files={"file": (image_path.name, img_bytes, "image/jpeg")},
            timeout=30,
        )
    except requests.RequestException as e:
        return {"status": "error", "reason": str(e)}
    elapsed_ms = (time.time() - start) * 1000

    if resp.status_code != 200:
        return {"status": "error", "reason": f"HTTP {resp.status_code}", "elapsed_ms": elapsed_ms}

    data = resp.json()

    result = {
        "image": image_path.name,
        "expected": expected,
        "elapsed_ms": round(elapsed_ms, 1),
        "api_time_ms": data.get("processing_time_ms"),
        "success": data.get("success", False),
        "method": data.get("method"),
        "ocr_name": data.get("ocr_name"),
        "ocr_number": data.get("ocr_number"),
        "detected_language": data.get("detected_language"),
        "confidence": data.get("confidence"),
    }

    if not data.get("success"):
        result["status"] = "fail_no_match"
        return result

    top = data.get("top_match", {})
    result["matched_name"] = top.get("name")
    result["matched_set"] = top.get("set_id")
    result["matched_number"] = top.get("collector_number")
    result["matched_language"] = top.get("language")

    # Check correctness
    expected_set = expected["set_id"]
    matched_set = top.get("set_id", "")

    # ZH-TW cards: DB stores set_id with "tw-" prefix (e.g. "tw-SV10")
    # but filename has no prefix (e.g. "zh-tw_SV10-086.jpg")
    if expected["language"] == "zh-tw" and not expected_set.startswith("tw-"):
        expected_set = f"tw-{expected_set}"

    correct_set = matched_set.lower() == expected_set.lower()
    # Some JP cards have collector_number=None in DB — compare by tcgdex_id if available
    if expected.get("collector_number") is not None:
        correct_number = top.get("collector_number") == expected["collector_number"]
    else:
        correct_number = True  # can't verify, trust set match

    # Also check by tcgdex_id if we have it (most reliable)
    correct_by_id = top.get("tcgdex_id") == expected.get("tcgdex_id") if expected.get("tcgdex_id") else False

    result["correct_number"] = correct_number
    result["correct_set"] = correct_set
    result["correct"] = correct_by_id or (correct_number and correct_set)

    # URLs
    result["cardmarket_url"] = top.get("cardmarket_url", "")
    result["tcgplayer_url"] = top.get("tcgplayer_url", "")
    result["pricecharting_url"] = top.get("pricecharting_url", "")
    result["has_cardmarket_url"] = bool(top.get("cardmarket_url"))
    result["has_tcgplayer_url"] = bool(top.get("tcgplayer_url"))
    result["has_pricecharting_url"] = bool(top.get("pricecharting_url"))

    # Prices
    result["price_trend_eur"] = top.get("price_trend")
    result["price_usd"] = top.get("price_usd")

    if check_urls and top.get("cardmarket_url"):
        result["cardmarket_url_check"] = check_url(top["cardmarket_url"])

    result["status"] = "correct" if result["correct"] else "wrong_match"
    return result


def main():
    check_urls = "--check-urls" in sys.argv
    seed = 42
    for arg in sys.argv[1:]:
        if arg.startswith("--seed="):
            seed = int(arg.split("=")[1])
    random.seed(seed)

    # Quick health check
    try:
        resp = requests.get(f"{API_BASE}/docs", timeout=5)
        if resp.status_code != 200:
            print(f"Server not ready at {API_BASE}")
            sys.exit(1)
    except requests.RequestException:
        print(f"Cannot connect to {API_BASE}. Start the server first.")
        sys.exit(1)

    cards = pick_random_cards(N_CARDS)

    results = []
    stats = {"correct": 0, "wrong_match": 0, "fail_no_match": 0, "error": 0, "skip": 0}
    url_stats = {"has_cardmarket": 0, "has_tcgplayer": 0, "has_pricecharting": 0}
    lang_stats = {"en": {"total": 0, "correct": 0}, "ja": {"total": 0, "correct": 0}, "zh-tw": {"total": 0, "correct": 0}}
    times = []

    print(f"\n{'='*80}")
    print(f"Testing {len(cards)} cards against /identify-v2")
    print(f"{'='*80}\n")

    for i, card_path in enumerate(cards, 1):
        result = test_card(card_path, check_urls=check_urls)
        results.append(result)

        status = result.get("status", "error")
        stats[status] = stats.get(status, 0) + 1

        if result.get("elapsed_ms"):
            times.append(result["elapsed_ms"])

        expected = result.get("expected", {})
        lang = expected.get("language", "?")
        if lang in lang_stats and status in ("correct", "wrong_match"):
            lang_stats[lang]["total"] += 1
            if status == "correct":
                lang_stats[lang]["correct"] += 1

        if result.get("has_cardmarket_url"):
            url_stats["has_cardmarket"] += 1
        if result.get("has_tcgplayer_url"):
            url_stats["has_tcgplayer"] += 1
        if result.get("has_pricecharting_url"):
            url_stats["has_pricecharting"] += 1

        # Progress
        icon = "+" if status == "correct" else "X" if status == "wrong_match" else "-"
        name = result.get("matched_name") or result.get("ocr_name") or "?"
        ms = result.get("elapsed_ms", 0)
        print(f"  [{i:3d}/{len(cards)}] {icon} {card_path.name:40s} -> {name:30s} ({ms:.0f}ms) [{status}]")

    # Summary
    tested = stats["correct"] + stats["wrong_match"] + stats["fail_no_match"]
    accuracy = stats["correct"] / tested * 100 if tested else 0
    avg_time = sum(times) / len(times) if times else 0

    print(f"\n{'='*80}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*80}")
    print(f"  Total tested:     {len(cards)}")
    print(f"  Correct:          {stats['correct']} ({accuracy:.1f}%)")
    print(f"  Wrong match:      {stats['wrong_match']}")
    print(f"  No match:         {stats['fail_no_match']}")
    print(f"  Errors:           {stats['error']}")
    print(f"  Skipped:          {stats['skip']}")
    print()
    print(f"  Avg response:     {avg_time:.0f}ms")
    if times:
        print(f"  Min/Max:          {min(times):.0f}ms / {max(times):.0f}ms")
    print()

    print("  By language:")
    for lang, s in lang_stats.items():
        if s["total"] > 0:
            pct = s["correct"] / s["total"] * 100
            print(f"    {lang:6s}: {s['correct']}/{s['total']} ({pct:.0f}%)")

    print()
    print("  URL coverage (of successful matches):")
    matched = stats["correct"] + stats["wrong_match"]
    if matched:
        print(f"    CardMarket:     {url_stats['has_cardmarket']}/{matched} ({url_stats['has_cardmarket']/matched*100:.0f}%)")
        print(f"    TCGPlayer:      {url_stats['has_tcgplayer']}/{matched} ({url_stats['has_tcgplayer']/matched*100:.0f}%)")
        print(f"    PriceCharting:  {url_stats['has_pricecharting']}/{matched} ({url_stats['has_pricecharting']/matched*100:.0f}%)")

    if check_urls:
        cm_checked = [r for r in results if "cardmarket_url_check" in r]
        cm_valid = [r for r in cm_checked if r["cardmarket_url_check"].get("valid")]
        print(f"\n    CardMarket URL validation: {len(cm_valid)}/{len(cm_checked)} reachable")

    # Save detailed results
    output_path = Path("test_100_results.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"stats": stats, "url_stats": url_stats, "lang_stats": lang_stats, "results": results}, f, indent=2, ensure_ascii=False)
    print(f"\n  Detailed results saved to {output_path}")

    # Print wrong matches for debugging
    wrong = [r for r in results if r.get("status") == "wrong_match"]
    if wrong:
        print(f"\n{'='*80}")
        print(f"WRONG MATCHES ({len(wrong)}):")
        print(f"{'='*80}")
        for r in wrong:
            exp = r["expected"]
            print(f"  {r['image']}")
            print(f"    Expected: {exp['set_id']}-{exp['collector_number']} ({exp['language']})")
            print(f"    Got:      {r.get('matched_set')}-{r.get('matched_number')} ({r.get('matched_language')})")
            print(f"    OCR:      name={r.get('ocr_name')}, num={r.get('ocr_number')}")
            print()


if __name__ == "__main__":
    main()
