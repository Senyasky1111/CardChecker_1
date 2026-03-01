"""Quick coverage check script."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

conn = sqlite3.connect("data/cards.db")
conn.row_factory = sqlite3.Row

print("=== Coverage Report ===\n")

for lang, label in [("en", "EN"), ("ja", "JP"), ("zh-tw", "TW")]:
    total = conn.execute("SELECT COUNT(*) FROM cards WHERE language=?", (lang,)).fetchone()[0]

    has_eng = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE language=? AND eng_name IS NOT NULL AND eng_name != ''",
        (lang,)
    ).fetchone()[0]

    has_cm = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE language=? AND cm_id_product IS NOT NULL AND cm_id_product > 0",
        (lang,)
    ).fetchone()[0]

    enriched = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE language=? AND enriched_at IS NOT NULL AND enriched_at != ''",
        (lang,)
    ).fetchone()[0]

    has_tcg = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE language=? AND tcgplayer_id IS NOT NULL AND tcgplayer_id > 0",
        (lang,)
    ).fetchone()[0]

    # Cards with eng_name but no CM ID (searchable gap)
    eng_no_cm = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE language=? AND eng_name IS NOT NULL AND eng_name != '' AND (cm_id_product IS NULL OR cm_id_product = 0)",
        (lang,)
    ).fetchone()[0]

    # Cards with CM but not enriched
    cm_not_enriched = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE language=? AND cm_id_product IS NOT NULL AND cm_id_product > 0 AND (enriched_at IS NULL OR enriched_at = '')",
        (lang,)
    ).fetchone()[0]

    # Cards with eng_name but not enriched
    eng_not_enriched = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE language=? AND eng_name IS NOT NULL AND eng_name != '' AND (enriched_at IS NULL OR enriched_at = '')",
        (lang,)
    ).fetchone()[0]

    no_eng = total - has_eng

    print(f"{label}: {total} total")
    print(f"  eng_name:    {has_eng:6d} ({100*has_eng/total:.1f}%)  |  missing: {no_eng}")
    print(f"  CM ID:       {has_cm:6d} ({100*has_cm/total:.1f}%)  |  missing: {total - has_cm}")
    print(f"  enriched:    {enriched:6d} ({100*enriched/total:.1f}%)")
    print(f"  TCGPlayer:   {has_tcg:6d} ({100*has_tcg/total:.1f}%)")
    print(f"  eng+noCM:    {eng_no_cm:6d}  (searchable gap)")
    print(f"  CM+notEnr:   {cm_not_enriched:6d}  (can bulk enrich)")
    print(f"  eng+notEnr:  {eng_not_enriched:6d}  (can search enrich)")
    print()

# Price stats
pe_total = conn.execute("SELECT COUNT(*) FROM prices_external").fetchone()[0]
ext_ids = conn.execute("SELECT COUNT(*) FROM card_external_ids").fetchone()[0]
print(f"Price rows: {pe_total}")
print(f"External IDs: {ext_ids}")

conn.close()
