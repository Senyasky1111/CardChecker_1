"""Shared harness for The Card API pilot — used by all pilot agents so matching
logic is IDENTICAL across strata.

Pipeline per card:
  build_query -> search_sales (paginated) -> match_records (precise filter) ->
  medians (raw + per-grade, shipping-folded) -> compare vs our eBay-USD / tcgplayer price.

CLI:
  python scripts/tca_pilot_lib.py --stratum EN_HIGH --out out.json
  python scripts/tca_pilot_lib.py --ids swsh4-025,base1-4 --out out.json

Strata (50 cards total): EN_HIGH (17), EN_MIDLOW (16), JP (17).
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://thecardapi.com/api/v1/market/sales"
DB = ROOT / "data" / "cards.db"

# FIX 7: widen LOT regex — two-card titles, "read"/"see photos", sealed/booster.
LOT_RE = re.compile(
    r"\b(lot|bundle|joblot|playset|set of|choose|pick|you pick|x\s?\d{1,3}\b|"
    r"\d{2,}\s?cards|proxy|custom|orica|sticker|jumbo|oversized|metal card|gold card|"
    r"read|see photos|see pics|sealed|booster|blister|pack fresh|elite trainer|etb)\b",
    re.I,
)
# two-card titles: "Charizard and Blastoise ... 4/102" or "Pikachu & Raichu 58/102"
TWO_CARD_RE = re.compile(r"\b\w+\s+(and|&)\s+\w+.*\d+\s*/\s*\d+", re.I)

MIN_PRICE_FLOOR = 1.50  # FIX 7: drop penny/junk records
LOW_N = 3               # FIX 3: per-grade bucket is "thin" below this


def load_key() -> str:
    for line in (ROOT / ".env.thecardapi").read_text(encoding="utf-8").splitlines():
        if line.startswith("THECARDAPI_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no THECARDAPI_KEY in .env.thecardapi")


def clean_name(name: str) -> str:
    name = re.sub(r"\s*\[.*?\]", "", name or "")
    name = re.sub(r"\s*\(.*?\)", "", name)
    return re.sub(r"\s+", " ", name).strip()


def num_variants(num, total) -> list[str]:
    """String forms a collector number can take in eBay titles."""
    out = []
    if num is None:
        return out
    s = str(num).strip()
    out.append(s)
    if s.isdigit():
        out.append(f"{int(s):03d}")
        if total:
            out.append(f"{s}/{total}")
            out.append(f"{int(s):03d}/{int(total):03d}")
    return list(dict.fromkeys(out))


def numtotal_variants(num, total) -> list[str]:
    """Only the strong `num/total` forms (required when set_total is known)."""
    if num is None or not total:
        return []
    s = str(num).strip()
    if not s.isdigit():
        return []
    return list(dict.fromkeys([f"{s}/{total}", f"{int(s):03d}/{int(total):03d}"]))


def _norm_code(x) -> list[str]:
    """Normalized token forms for a set abbreviation / set_id.

    Produces lowercased variants: as-is, hyphen-stripped, and space-stripped.
    e.g. 'XY10-B' -> ['xy10-b','xy10b','xy10 b']; 'S-P' -> ['s-p','sp','s p'].
    """
    if not x:
        return []
    s = str(x).strip().lower()
    if not s:
        return []
    out = [s]
    if "-" in s:
        out.append(s.replace("-", ""))
        out.append(s.replace("-", " "))
    return list(dict.fromkeys(out))


def set_code_variants(c: dict) -> list[str]:
    """All abbreviation / set_id token forms usable as a disambiguator."""
    out: list[str] = []
    out += _norm_code(c.get("abbreviation"))
    out += _norm_code(c.get("set_id"))
    return list(dict.fromkeys(out))


def _title_contains_code(title: str, variants: list[str]) -> bool:
    """Word-boundary-ish match of a set code in a title (guards against
    a short code being a substring of a longer word)."""
    for v in variants:
        if not v:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(v)}(?![a-z0-9])", title):
            return True
    return False


def build_query(c: dict) -> str:
    lang = c["language"]
    nm = clean_name(c["eng_name"] if lang != "en" else (c["name"] or c["eng_name"]))
    parts = [nm]
    codes = set_code_variants(c)
    if lang == "ja":
        parts.append("Japanese")
        # FIX 5: include the set abbreviation/code to improve JP recall.
        if codes:
            parts.append(codes[0])
    nv = num_variants(c["collector_number"], c["set_total"])
    if nv:
        parts.append(nv[0])  # keep query loose; precision comes from match filter
    elif codes:
        # FIX 4: no number — lean on the set/promo code in the query too.
        parts.append(codes[0])
    return " ".join(p for p in parts if p)


def search_sales(
    key: str, q: str, date_from: str, limit: int = 200, max_pages: int = 3, cap: int = 300
) -> tuple[int, list[dict]]:
    """FIX 6: paginate. Fetch up to `max_pages` via next_cursor, capping total
    fetched records at ~`cap` to stay cheap. Returns (api_total, records)."""
    collected: list[dict] = []
    cursor = None
    total = 0
    truncated = False
    for _page in range(max_pages):
        params = {"q": q, "limit": limit, "date_from": date_from, "sort": "date_desc"}
        if cursor:
            params["cursor"] = cursor
        url = f"{BASE}?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"x-market-api-key": key})
        last = ""
        page_data = None
        page_json = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    page_json = json.loads(r.read())
                    page_data = page_json.get("data", [])
                    break
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode()[:200]
                except Exception:  # noqa
                    pass
                # A 429 can be a transient rate-limit (retry) OR a terminal daily
                # quota exhaustion — the latter must be surfaced, not silently retried.
                if e.code == 429 and "daily" not in body.lower() and "limit reached" not in body.lower():
                    time.sleep(2 * (attempt + 1))
                    last = f"HTTP 429 {body}"
                    continue
                return -1, [{"_error": f"HTTP {e.code}", "_body": body}]
            except Exception as e:  # noqa
                time.sleep(1)
                last = str(e) or "unknown request error"
        if page_data is None:
            if collected:
                break  # keep what we have from earlier pages
            return -1, [{"_error": last}]
        total = page_json.get("pagination", {}).get("total", total) or total
        collected.extend(page_data)
        cursor = page_json.get("pagination", {}).get("next_cursor")
        if not cursor or not page_data:
            break
        if len(collected) >= cap:
            truncated = True
            break
        time.sleep(0.2)
    if total > len(collected):
        truncated = True
    if truncated and collected:
        collected[0].setdefault("_truncated", True)
    return total, collected


def match_record(rec: dict, c: dict) -> bool:
    """Precise filter: is this eBay sale actually OUR card?"""
    title = (rec.get("title") or "").lower()
    if not title or LOT_RE.search(title) or TWO_CARD_RE.search(title):
        return False
    lang = c["language"]
    name = clean_name(c["eng_name"] if lang != "en" else (c["name"] or c["eng_name"]))
    # primary name token (skip trailing type words for the REQUIRED token)
    toks = [t for t in re.split(r"[^\w']+", name.lower()) if t]
    stop = {"ex", "gx", "v", "vmax", "vstar", "gl", "lv", "star", "prime", "the"}
    core = [t for t in toks if t not in stop] or toks
    if not all(t in title for t in core[:2]):  # require up to 2 core name tokens
        return False

    codes = set_code_variants(c)
    # Language gate.
    if lang == "ja":
        # FIX 5: accept ANY JP signal, not just literal "japanese".
        jp_signals = ["japanese", "japan", " jp ", "jpn"]
        has_signal = any(sig in title for sig in jp_signals) or _title_contains_code(title, codes)
        if not has_signal:
            return False
    else:
        # EN card must NOT be the JP print.
        if "japanese" in title:
            return False

    # FIX 1: when set_total is known, REQUIRE the num/total form.
    strong = numtotal_variants(c["collector_number"], c["set_total"])
    if strong:
        return any(v in title for v in strong)

    # No set_total but we have a number -> bare word-boundary number is allowed.
    # Accept the zero-padded form too: JP titles print "070" / "028" while our
    # collector_number is stored bare ("70" / "28"); a plain `(?<!\d)70(?!\d)`
    # misses "070" because the 7 is preceded by the leading-zero digit.
    if c["collector_number"] is not None:
        bare = str(c["collector_number"]).strip()
        forms = {bare}
        if bare.isdigit():
            forms.add(f"{int(bare):03d}")   # 28 -> 028, 70 -> 070
        return any(re.search(rf"(?<!\d){re.escape(f)}(?!\d)", title) for f in forms)

    # FIX 4: promos / no collector_number — never match by name alone.
    # Require a set/promo code present in BOTH query and title.
    if not codes:
        return False  # nothing to disambiguate on
    return _title_contains_code(title, codes)


def can_disambiguate(c: dict) -> bool:
    """FIX 4: a card with no number AND no usable set/promo code cannot be
    matched safely — the harness should skip it rather than return garbage."""
    if c["collector_number"] is not None:
        return True
    return bool(set_code_variants(c))


def classify(rec: dict) -> str:
    g, grader = rec.get("grade"), rec.get("grader")
    if g and grader:
        return f"{str(grader).upper()}_{str(g).replace('.', '_')}"
    return "RAW"


def price_of(rec: dict) -> float | None:
    try:
        return float(rec["price"])
    except (KeyError, TypeError, ValueError):
        return None


def total_price(rec: dict) -> float | None:
    """FIX 2: item price + shipping (shipping treated as 0 when absent)."""
    p = price_of(rec)
    if p is None:
        return None
    try:
        ship = float(rec.get("shipping_price") or 0)
    except (TypeError, ValueError):
        ship = 0.0
    return round(p + ship, 2)


def our_price(conn, tid: str) -> dict:
    """Our stored comps for comparison (prefer USD eBay, then tcgplayer NM)."""
    out = {}
    rows = conn.execute(
        "SELECT marketplace,condition,currency,price_avg,price_trend,avg_30d,snapshot_date "
        "FROM prices_external WHERE tcgdex_id=? AND currency='USD'", (tid,)).fetchall()
    for r in rows:
        r = dict(r)
        key = f"{r['marketplace']}:{r['condition']}"
        val = r["avg_30d"] or r["price_avg"] or _f(r["price_trend"])
        if val:
            out[key] = {"price": round(val, 2), "date": r["snapshot_date"]}
    return out


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def get_cards(conn, ids: list[str]) -> list[dict]:
    qs = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT c.tcgdex_id,c.name,c.eng_name,c.collector_number,c.language,c.set_id,"
        f"c.set_total,c.top_price_usd,c.top_price_eur,c.has_graded,s.name set_name,s.abbreviation "
        f"FROM cards c LEFT JOIN sets s ON c.set_id=s.set_id AND s.language=c.language "
        f"WHERE c.tcgdex_id IN ({qs})", ids).fetchall()
    return [dict(r) for r in rows]


def stratum_ids(conn, name: str) -> list[str]:
    if name == "EN_HIGH":
        sql = ("SELECT tcgdex_id FROM cards WHERE language='en' AND name IS NOT NULL "
               "AND top_price_usd IS NOT NULL ORDER BY top_price_usd DESC LIMIT 17")
    elif name == "EN_MIDLOW":
        sql = ("SELECT tcgdex_id FROM cards WHERE language='en' AND name IS NOT NULL "
               "AND top_price_usd BETWEEN 3 AND 40 ORDER BY tcgdex_id LIMIT 16")
    elif name == "JP":
        sql = ("SELECT tcgdex_id FROM cards WHERE language='ja' AND eng_name IS NOT NULL "
               "ORDER BY COALESCE(top_price_usd,top_price_eur) DESC LIMIT 17")
    else:
        raise SystemExit(f"unknown stratum {name}")
    return [r[0] for r in conn.execute(sql).fetchall()]


def median(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 2) if vals else None


def run_cards(ids: list[str], date_from: str = "2026-04-01") -> list[dict]:
    key = load_key()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cards = get_cards(conn, ids)
    results = []
    for c in cards:
        # FIX 4: skip cards we cannot disambiguate at all.
        if not can_disambiguate(c):
            results.append({
                "tcgdex_id": c["tcgdex_id"],
                "name": c["eng_name"] or c["name"],
                "language": c["language"],
                "set": c["set_name"], "num": c["collector_number"],
                "skipped": "no_disambiguator",
            })
            continue

        q = build_query(c)
        total, data = search_sales(key, q, date_from)
        time.sleep(0.25)
        if total == -1 and data and isinstance(data[0], dict) and "_error" in data[0]:
            results.append({"tcgdex_id": c["tcgdex_id"], "query": q, "error": data[0]})
            continue
        truncated = bool(data and isinstance(data[0], dict) and data[0].get("_truncated"))

        matched = [r for r in data if match_record(r, c)]

        # FIX 2 + 7: fold shipping into price; drop RAW penny/junk (< $1.50).
        by_grade_tp: dict[str, list[float]] = {}   # total price (shipping-folded)
        by_grade_item: dict[str, list[float]] = {}  # item-only price
        kept = []
        for r in matched:
            g = classify(r)
            tp = total_price(r)
            item = price_of(r)
            if g == "RAW" and tp is not None and tp < MIN_PRICE_FLOOR:
                continue  # penny/junk
            by_grade_tp.setdefault(g, []).append(tp)
            by_grade_item.setdefault(g, []).append(item)
            kept.append(r)
        matched = kept

        raw_median = median(by_grade_tp.get("RAW", []))

        medians = {}
        for g, tps in by_grade_tp.items():
            n = len([x for x in tps if x is not None])
            entry = {
                "median_usd": median(tps),                         # shipping-folded
                "median_item_usd": median(by_grade_item.get(g, [])),
                "n": n,
            }
            # FIX 3: mark thin buckets.
            if n < LOW_N:
                entry["low_n"] = True
            # FIX 3: monotonicity guard — graded median below RAW is a mismatch.
            if g != "RAW" and raw_median is not None and entry["median_usd"] is not None:
                if entry["median_usd"] < raw_median:
                    entry["suspect_monotonicity"] = True
            medians[g] = entry

        m_dates = sorted(r.get("sale_date") for r in matched if r.get("sale_date"))
        date_range = [m_dates[0], m_dates[-1]] if m_dates else None
        results.append({
            "tcgdex_id": c["tcgdex_id"],
            "name": c["eng_name"] or c["name"],
            "language": c["language"],
            "set": c["set_name"], "num": c["collector_number"],
            "query": q,
            "n_raw_api": total, "n_returned": len(data), "n_matched": len(matched),
            "truncated": truncated,
            "matched_date_range": date_range,
            "medians_by_grade": medians,
            "our_price_usd": our_price(conn, c["tcgdex_id"]),
            "top_price_usd": c["top_price_usd"],
            "sample_urls": [r.get("listing_url") for r in matched[:2]],
            "sample_titles": [r.get("title") for r in matched[:3]],
        })
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stratum")
    ap.add_argument("--ids")
    ap.add_argument("--out", required=True)
    ap.add_argument("--date-from", default="2026-04-01")
    a = ap.parse_args()
    conn = sqlite3.connect(DB)
    if a.stratum:
        ids = stratum_ids(conn, a.stratum)
    else:
        ids = a.ids.split(",")
    res = run_cards(ids, a.date_from)
    Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = sum(1 for r in res if r.get("n_matched"))
    skipped = sum(1 for r in res if r.get("skipped"))
    print(f"wrote {a.out}: {len(res)} cards, {ok} with >=1 matched sale, {skipped} skipped")


if __name__ == "__main__":
    main()
