import sqlite3, json, time, os, sys

"""
Prod-side catalog delta applier. Runs INSIDE the prod container:
  cat scripts/apply_catalog_delta.py | ssh root@HOST 'docker exec -i cardcheck-price-updater python - <tag>'

Reads /app/data/_sets_delta.json and /app/data/_cards_delta.json (each a list of
row dicts col->value) and INSERT OR IGNORE them into `sets` / `cards`.

INSERT OR IGNORE means: brand-new set_id / tcgdex_id rows are inserted; any row that
already exists on prod is left EXACTLY as-is (keeps its cron-written prices and its
precise join-based link columns). This never UPDATEs an existing row and never touches
the prices*/price_history tables, so it is safe to run without racing the nightly crons.

Whole-DB VACUUM INTO backup + integrity_check first (same guarantee as apply_links_prod.py).
Columns are intersected with the live prod schema, so a schema drift can't crash the insert.
"""

DB = "/app/data/cards.db"
tag = sys.argv[1] if len(sys.argv) > 1 else "catalog"
ts = time.strftime("%Y%m%d-%H%M%S")

def load(name):
    p = "/app/data/" + name
    if not os.path.exists(p):
        print(f"[{tag}] MISSING {p} -> treating as empty")
        return []
    return json.load(open(p, encoding="utf-8"))

sets_delta = load("_sets_delta.json")
cards_delta = load("_cards_delta.json")
print(f"[{tag}] sets_delta={len(sets_delta)} cards_delta={len(cards_delta)}")

con = sqlite3.connect(DB)

# --- backup ---
bak = f"/app/data/cards.db.pre-{tag}-{ts}"
con.execute(f"VACUUM INTO '{bak}'")
b = sqlite3.connect(bak)
ok = b.execute("PRAGMA integrity_check").fetchone()[0]
b.close()
print(f"[{tag}] backup: {bak}  integrity={ok}  size={os.path.getsize(bak)}")
assert ok == "ok", "backup integrity failed -- ABORT"

cur = con.cursor()

def table_cols(t):
    return [r[1] for r in cur.execute(f"PRAGMA table_info({t})").fetchall()]

def insert_ignore(table, rows):
    if not rows:
        return 0, 0
    valid = set(table_cols(table))
    before = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    cur.execute("BEGIN")
    for row in rows:
        cols = [c for c in row.keys() if c in valid]
        if not cols:
            continue
        ph = ",".join("?" for _ in cols)
        cur.execute(
            f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({ph})",
            [row[c] for c in cols],
        )
    con.commit()
    after = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return before, after

sb, sa = insert_ignore("sets", sets_delta)
print(f"[{tag}] sets: {sb} -> {sa}  (+{sa-sb} new)")
cb, ca = insert_ignore("cards", cards_delta)
print(f"[{tag}] cards: {cb} -> {ca}  (+{ca-cb} new)")

# readback per language
for lang, n in cur.execute("SELECT language, COUNT(*) FROM cards GROUP BY language").fetchall():
    print(f"[{tag}]   cards[{lang}] = {n}")
con.close()
print(f"[{tag}] APPLIED OK  backup_ts={ts}")
