"""The Card API sold-comps pipeline.

Ingests real eBay/Goldin SOLD Pokemon sales, matches them to our catalog (reusing
the hardened matcher in scripts/tca_pilot_lib.py), and aggregates per-card / per-grade
sold medians into cards.db so the existing /card/{id}/prices endpoint surfaces them
(marketplace='ebay' -> eBay block; graded conditions -> graded block) plus clickable
recent comps in ebay_sold_listings.

Raw firehose lives in a DEDICATED data/sales.db (never bolted onto cards.db).

Subcommands:
    ingest    pull q=pokemon firehose (newest-first, cursor, budget-capped) -> sales_raw
    match     map unmatched sales_raw -> tcgdex_id -> sales_match
    aggregate per card/grade sold medians -> cards.db prices_external + ebay_sold_listings
    run       ingest -> match -> aggregate

Key: env THECARDAPI_KEY, else .env.thecardapi (THECARDAPI_KEY=...).

Usage:
    python scripts/thecardapi_sold.py run --budget 2000 --sales-db data/sales.db --cards-db data/cards.db
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import statistics
import time
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# tca_pilot_lib lives in scripts/. Make the import work whether this file runs from
# scripts/ (repo/image) or from the mounted /app/data volume (durable prod cron).
for _p in (str(Path(__file__).resolve().parent), "/app/scripts"):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import tca_pilot_lib as tca  # match_record, classify, total_price, clean_name, can_disambiguate

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://www.thecardapi.com/api/v1/market/sales"
MATCHER_VERSION = "tca-2026-07-06"
GRADE_PREFIXES = ("PSA_", "BGS_", "CGC_", "SGC_", "ACE_", "TAG_", "PGS_", "AOG_", "EGS_", "CGS_", "GSG_", "PCA_")


def load_key() -> str:
    k = os.environ.get("THECARDAPI_KEY")
    if k:
        return k.strip()
    cands = [ROOT / ".env.thecardapi", ROOT / "data" / ".env.thecardapi",
             Path("/app/data/.env.thecardapi"), Path("data/.env.thecardapi"),
             Path(".env.thecardapi")]
    for p in cands:
        if p.exists():
            for line in p.read_text().splitlines():
                if line.startswith("THECARDAPI_KEY="):
                    return line.split("=", 1)[1].strip()
    raise SystemExit("No THECARDAPI_KEY (env or .env.thecardapi)")


# ── sales.db schema ──────────────────────────────────────────────────
def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
    CREATE TABLE IF NOT EXISTS sales_raw (
        sale_uid TEXT PRIMARY KEY, platform TEXT, title TEXT NOT NULL,
        price REAL, currency TEXT, grade TEXT, grader TEXT, cert TEXT,
        sale_date TEXT, sold_at TEXT, listing_type TEXT, listing_url TEXT,
        image_url TEXT, fetched_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_sr_saledate ON sales_raw(sale_date);
    CREATE TABLE IF NOT EXISTS sync_state (
        stream TEXT PRIMARY KEY, backfill_cursor TEXT, oldest_date TEXT,
        records_today INTEGER DEFAULT 0, records_day TEXT, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS sales_match (
        sale_uid TEXT NOT NULL, tcgdex_id TEXT, matcher_version TEXT NOT NULL,
        confidence TEXT, matched_at TEXT, PRIMARY KEY (sale_uid, matcher_version)
    );
    CREATE INDEX IF NOT EXISTS idx_sm_card ON sales_match(tcgdex_id, matcher_version);
    """)
    con.commit()


# ── ingest ───────────────────────────────────────────────────────────
def _api_get(key: str, params: dict, retries: int = 4) -> dict | None:
    url = f"{BASE}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-market-api-key": key, "Accept": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()[:200]
            except Exception:
                pass
            if e.code == 429 and "daily" not in body.lower() and "limit" not in body.lower():
                time.sleep(3 * (attempt + 1))
                continue
            print(f"  [HTTP {e.code}] {body}")
            return {"_terminal": True} if e.code == 429 else None
        except Exception as e:
            time.sleep(2 * (attempt + 1))
    return None


def ingest(sales_db: str, budget: int, price_min: float = 1.50, q: str = "pokemon") -> int:
    key = load_key()
    con = sqlite3.connect(sales_db); con.row_factory = sqlite3.Row
    ensure_schema(con)
    st = con.execute("SELECT * FROM sync_state WHERE stream='pokemon'").fetchone()
    cursor = st["backfill_cursor"] if st else None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    records_today = st["records_today"] if st and st["records_day"] == today else 0

    pulled = 0
    while pulled < budget:
        params = {"q": q, "sort": "date_desc", "limit": 1000, "price_min": price_min}
        if cursor:
            params["cursor"] = cursor
        data = _api_get(key, params)
        if not data or data.get("_terminal"):
            print("  stopping (daily quota / error)" if data else "  stopping (fetch failed)")
            break
        rows = data.get("data", [])
        if not rows:
            break
        oldest = None
        for r in rows:
            uid = r.get("id") or f"{r.get('listing_url')}|{r.get('sale_date')}|{r.get('price')}"
            con.execute(
                "INSERT OR IGNORE INTO sales_raw (sale_uid,platform,title,price,currency,grade,grader,"
                "cert,sale_date,sold_at,listing_type,listing_url,image_url,fetched_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (uid, r.get("platform"), r.get("title") or "", r.get("price"), r.get("currency"),
                 r.get("grade"), r.get("grader"), r.get("cert"), r.get("sale_date"), r.get("sold_at"),
                 r.get("listing_type"), r.get("listing_url"), r.get("image_url"),
                 datetime.now(timezone.utc).isoformat()))
            oldest = r.get("sale_date") or oldest
        pulled += len(rows)
        records_today += len(rows)
        cursor = data.get("pagination", {}).get("next_cursor")
        con.execute(
            "INSERT INTO sync_state (stream,backfill_cursor,oldest_date,records_today,records_day,updated_at) "
            "VALUES ('pokemon',?,?,?,?,?) ON CONFLICT(stream) DO UPDATE SET "
            "backfill_cursor=excluded.backfill_cursor, oldest_date=excluded.oldest_date, "
            "records_today=excluded.records_today, records_day=excluded.records_day, updated_at=excluded.updated_at",
            (cursor, oldest, records_today, today, datetime.now(timezone.utc).isoformat()))
        con.commit()
        print(f"  +{len(rows)} (total this run {pulled}, oldest {oldest})")
        if not cursor:
            print("  reached window bottom (30d) — backfill complete; cursor reset")
            con.execute("UPDATE sync_state SET backfill_cursor=NULL WHERE stream='pokemon'")
            con.commit()
            break
        time.sleep(0.2)
    total = con.execute("SELECT COUNT(*) FROM sales_raw").fetchone()[0]
    print(f"ingest done: pulled {pulled} this run; sales_raw now {total} rows")
    con.close()
    return pulled


# ── match ────────────────────────────────────────────────────────────
STOP = {"ex", "gx", "v", "vmax", "vstar", "gl", "lv", "star", "prime", "the"}


def _card_core(c: dict) -> list[str]:
    lang = c["language"]
    name = tca.clean_name(c["eng_name"] if lang != "en" else (c["name"] or c["eng_name"]))
    toks = [t for t in re.split(r"[^\w']+", name.lower()) if t]
    core = [t for t in toks if t not in STOP] or toks
    return core[:2]


def match(sales_db: str, cards_db: str) -> int:
    scon = sqlite3.connect(sales_db); scon.row_factory = sqlite3.Row
    ensure_schema(scon)
    ccon = sqlite3.connect(cards_db); ccon.row_factory = sqlite3.Row
    cards = [dict(r) for r in ccon.execute(
        "SELECT c.tcgdex_id,c.name,c.eng_name,c.collector_number,c.language,c.set_id,c.set_total,"
        "s.abbreviation FROM cards c LEFT JOIN sets s ON c.set_id=s.set_id AND s.language=c.language")]
    # inverted index: primary name token -> [card]
    index: dict[str, list[dict]] = {}
    for c in cards:
        if not tca.can_disambiguate(c):
            continue
        core = _card_core(c)
        if core:
            index.setdefault(core[0], []).append(c)

    todo = scon.execute(
        "SELECT r.sale_uid,r.title,r.grade,r.grader FROM sales_raw r "
        "LEFT JOIN sales_match m ON m.sale_uid=r.sale_uid AND m.matcher_version=? "
        "WHERE m.sale_uid IS NULL", (MATCHER_VERSION,)).fetchall()
    now = datetime.now(timezone.utc).isoformat()
    matched = 0
    for i, s in enumerate(todo):
        title = (s["title"] or "").lower()
        rec = {"title": s["title"], "grade": s["grade"], "grader": s["grader"]}
        toks = set(re.split(r"[^\w']+", title))
        found = None
        seen = set()
        for tok in toks:
            for c in index.get(tok, ()):
                if c["tcgdex_id"] in seen:
                    continue
                seen.add(c["tcgdex_id"])
                num = c["collector_number"]
                if num is not None and str(num) not in title:  # cheap pre-filter
                    continue
                if tca.match_record(rec, c):
                    found = c
                    break
            if found:
                break
        conf = "strong" if (found and found["set_total"]) else ("weak" if found else None)
        scon.execute(
            "INSERT OR IGNORE INTO sales_match (sale_uid,tcgdex_id,matcher_version,confidence,matched_at) "
            "VALUES (?,?,?,?,?)", (s["sale_uid"], found["tcgdex_id"] if found else None, MATCHER_VERSION, conf, now))
        if found:
            matched += 1
        if (i + 1) % 20000 == 0:
            scon.commit(); print(f"  matched {matched}/{i+1}...")
    scon.commit()
    print(f"match done: {matched}/{len(todo)} new sales matched to a card")
    scon.close(); ccon.close()
    return matched


# ── aggregate ────────────────────────────────────────────────────────
def _bucket(grade, grader) -> str:
    if grade and grader:
        return f"{str(grader).upper()}_{str(grade).replace('.', '_')}"
    return "NEAR_MINT"  # raw sale


def aggregate(sales_db: str, cards_db: str) -> None:
    scon = sqlite3.connect(sales_db); scon.row_factory = sqlite3.Row
    ccon = sqlite3.connect(cards_db); ccon.row_factory = sqlite3.Row
    ccon.execute("PRAGMA busy_timeout=15000")
    rows = scon.execute("""
        SELECT m.tcgdex_id, r.grade, r.grader, r.price, r.title, r.listing_url, r.sale_date, r.sale_uid
        FROM sales_match m JOIN sales_raw r ON r.sale_uid=m.sale_uid
        WHERE m.matcher_version=? AND m.tcgdex_id IS NOT NULL AND r.price > 0
    """, (MATCHER_VERSION,)).fetchall()

    from collections import defaultdict
    groups: dict[tuple, list] = defaultdict(list)
    comps: dict[str, list] = defaultdict(list)
    for r in rows:
        b = _bucket(r["grade"], r["grader"])
        groups[(r["tcgdex_id"], b)].append(r["price"])
        comps[r["tcgdex_id"]].append(r)

    today = datetime.now(timezone.utc).isoformat()
    snap = today[:10]
    n_price = 0
    for (tid, bucket), prices in groups.items():
        med = round(statistics.median(prices), 2)
        marketplace = "ebay"
        ccon.execute("""
            INSERT OR REPLACE INTO prices_external
            (tcgdex_id, source, marketplace, condition, country, currency,
             price_avg, price_low, price_high, price_trend, avg_1d, avg_7d, avg_30d,
             sale_count, confidence, snapshot_date, updated_at)
            VALUES (?, 'thecardapi', ?, ?, 'ALL', 'USD', ?, ?, ?, '', NULL, NULL, NULL, ?, 'sold', ?, ?)
        """, (tid, marketplace, bucket, med, round(min(prices), 2), round(max(prices), 2),
              len(prices), snap, today))
        n_price += 1

    # recent comps with links (most recent 20 per card). ebay_sold_listings already
    # exists (src/db.py, "Phase 2"); add a `source` column if missing so we can
    # replace only our rows without touching any other writer.
    have = {r[1] for r in ccon.execute("PRAGMA table_info(ebay_sold_listings)")}
    if "source" not in have:
        ccon.execute("ALTER TABLE ebay_sold_listings ADD COLUMN source TEXT")
    ccon.execute("DELETE FROM ebay_sold_listings WHERE source='thecardapi'")
    n_comp = 0
    for tid, rs in comps.items():
        for r in sorted(rs, key=lambda x: x["sale_date"] or "", reverse=True)[:20]:
            ccon.execute("INSERT INTO ebay_sold_listings "
                         "(tcgdex_id,listing_url,title,price,currency,condition,grader,grade,sold_at,fetched_at,source) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?, 'thecardapi')",
                         (tid, r["listing_url"], r["title"], r["price"], "USD",
                          _bucket(r["grade"], r["grader"]), r["grader"], r["grade"], r["sale_date"], today))
            n_comp += 1
    ccon.commit()
    print(f"aggregate done: wrote {n_price} price rows across {len(comps)} cards, {n_comp} recent comps")
    scon.close(); ccon.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["ingest", "match", "aggregate", "run"])
    ap.add_argument("--sales-db", default="data/sales.db")
    ap.add_argument("--cards-db", default="data/cards.db")
    ap.add_argument("--budget", type=int, default=2000)
    ap.add_argument("--price-min", type=float, default=1.50)
    a = ap.parse_args()
    if a.cmd in ("ingest", "run"):
        ingest(a.sales_db, a.budget, a.price_min)
    if a.cmd in ("match", "run"):
        match(a.sales_db, a.cards_db)
    if a.cmd in ("aggregate", "run"):
        aggregate(a.sales_db, a.cards_db)


if __name__ == "__main__":
    main()
