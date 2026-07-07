import sqlite3, json, time, os, sys

"""
Generic prod link-writer. Runs INSIDE the prod container:
  cat scripts/apply_links_prod.py | ssh root@... 'docker exec -i cardcheck-price-updater python - <tag> <writes_filename>'

Reads /app/data/<writes_filename> (list of {tcgdex_id, language, <fields>}) and
applies any of these known columns present per row:
  pricecharting_url, tcgplayer_id, tcgplayer_url, cm_id_product, cm_url_slug
Backs up the whole DB (VACUUM INTO) + snapshots the touched columns first.
"""

DB = "/app/data/cards.db"
KNOWN = ("pricecharting_url", "tcgplayer_id", "tcgplayer_url",
         "cm_id_product", "cm_url_slug")

tag = sys.argv[1] if len(sys.argv) > 1 else "links"
writes_file = "/app/data/" + (sys.argv[2] if len(sys.argv) > 2 else "_apply_writes.json")

writes = json.load(open(writes_file, encoding="utf-8"))
print(f"[{tag}] write-set rows: {len(writes)}")

# which columns appear
cols = [c for c in KNOWN if any(c in w for w in writes)]
print(f"[{tag}] columns to update: {cols}")

con = sqlite3.connect(DB)
ts = time.strftime("%Y%m%d-%H%M%S")
bak = f"/app/data/cards.db.pre-{tag}-{ts}"
con.execute(f"VACUUM INTO '{bak}'")
b = sqlite3.connect(bak)
ok = b.execute("PRAGMA integrity_check").fetchone()[0]
b.close()
print(f"[{tag}] backup: {bak}  integrity={ok}  size={os.path.getsize(bak)}")
assert ok == "ok", "backup integrity failed -- ABORT"

cur = con.cursor()
# snapshot touched columns for these rows
snap_cols = ",".join(["tcgdex_id", "language"] + cols)
snap = []
q = f"SELECT {snap_cols} FROM cards WHERE tcgdex_id=? AND language=?"
for w in writes:
    r = cur.execute(q, (w["tcgdex_id"], w["language"])).fetchone()
    if r:
        snap.append(r)
json.dump(snap, open(f"/app/data/_snapshot-{tag}-{ts}.json", "w", encoding="utf-8"),
          ensure_ascii=False)
print(f"[{tag}] field snapshot: {len(snap)} rows")

applied = 0
cur.execute("BEGIN")
for w in writes:
    sets = [(c, w[c]) for c in cols if c in w]
    if not sets:
        continue
    assign = ", ".join(f"{c}=?" for c, _ in sets)
    vals = [v for _, v in sets] + [w["tcgdex_id"], w["language"]]
    cur.execute(f"UPDATE cards SET {assign} WHERE tcgdex_id=? AND language=?", vals)
    applied += cur.rowcount
con.commit()
print(f"[{tag}] rows updated: {applied}")

# coverage readback
for c in cols:
    rows = cur.execute(
        f"SELECT language, COUNT(*) FROM cards WHERE {c} IS NOT NULL AND {c}<>'' "
        f"AND {c}<>0 GROUP BY language").fetchall()
    print(f"[{tag}] {c} populated:", dict(rows))
con.close()
print(f"[{tag}] APPLIED OK  backup_ts={ts}")
