"""Generate catalog delta files (_sets_delta.json, _cards_delta.json) from LOCAL cards.db.

Usage:
  ./venv/Scripts/python.exe scripts/gen_catalog_delta.py [--prod-ids data/_prod_ids.json] [--out-dir data]

If --prod-ids is given (a JSON {"set_ids": [...], "tcgdex_ids": [...]} fetched from prod),
only rows NOT already on prod are emitted (minimal delta). Otherwise ALL rows are emitted
(safe: the prod-side applier uses INSERT OR IGNORE, so existing rows are skipped).
"""
import sys, json, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.db import get_connection

ap = argparse.ArgumentParser()
ap.add_argument("--prod-ids", default=None)
ap.add_argument("--out-dir", default="data")
args = ap.parse_args()

con = get_connection(None)
con.row_factory = None  # use tuples + description

prod_sets = prod_cards = None
if args.prod_ids:
    d = json.load(open(args.prod_ids, encoding="utf-8"))
    prod_sets = set(d.get("set_ids", []))
    prod_cards = set(d.get("tcgdex_ids", []))
    print(f"prod has {len(prod_sets)} sets, {len(prod_cards)} cards -> emitting only new rows")

def dump(table, pk, skip_set):
    cur = con.execute(f"SELECT * FROM {table}")
    cols = [c[0] for c in cur.description]
    pk_i = cols.index(pk)
    rows = []
    for r in cur.fetchall():
        if skip_set is not None and r[pk_i] in skip_set:
            continue
        rows.append({c: v for c, v in zip(cols, r)})
    return rows

sets_rows = dump("sets", "set_id", prod_sets)
cards_rows = dump("cards", "tcgdex_id", prod_cards)

out = Path(args.out_dir)
json.dump(sets_rows, open(out / "_sets_delta.json", "w", encoding="utf-8"), ensure_ascii=False)
json.dump(cards_rows, open(out / "_cards_delta.json", "w", encoding="utf-8"), ensure_ascii=False)
print(f"wrote {out/'_sets_delta.json'}: {len(sets_rows)} sets")
print(f"wrote {out/'_cards_delta.json'}: {len(cards_rows)} cards")
sz = (out / "_cards_delta.json").stat().st_size
print(f"cards delta size: {sz/1e6:.1f} MB")
