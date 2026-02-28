"""
Populate sets.cm_expansion_id from existing price data.

For EN sets: derive cm_expansion_id from cards that have cm_id_product → prices.cm_expansion_id.
For JP/TW sets: attempt to map through shared card names with EN sets.

Run after build_card_database.py or whenever the database is rebuilt.
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("data/cards.db")


def populate_en_set_expansion_ids(conn: sqlite3.Connection) -> int:
    """Set cm_expansion_id for EN sets using prices table data."""
    # For each EN set, find the most common cm_expansion_id among its cards
    rows = conn.execute("""
        SELECT c.set_id, p.cm_expansion_id, COUNT(*) as cnt
        FROM cards c
        JOIN prices p ON c.cm_id_product = p.cm_id_product
        WHERE c.language = 'en' AND p.cm_expansion_id IS NOT NULL
        GROUP BY c.set_id, p.cm_expansion_id
        ORDER BY c.set_id, cnt DESC
    """).fetchall()

    mapping: dict[str, int] = {}
    for set_id, exp_id, cnt in rows:
        if set_id not in mapping:
            mapping[set_id] = exp_id

    updated = 0
    for set_id, exp_id in mapping.items():
        conn.execute(
            "UPDATE sets SET cm_expansion_id = ? WHERE set_id = ? AND language = 'en'",
            (exp_id, set_id),
        )
        updated += 1

    conn.commit()
    return updated


def populate_jp_tw_set_expansion_ids(conn: sqlite3.Connection) -> int:
    """Attempt to map JP/TW sets to cm_expansion_id via card name matching.

    Strategy: for each JP/TW set, find EN cards with matching eng_name + collector_number.
    The EN set with the most matches gives us the cm_expansion_id.
    Require at least 5 matching cards for confidence.
    """
    updated = 0

    for lang in ("ja", "zh-tw"):
        # Find best EN set match for each JP/TW set
        rows = conn.execute("""
            SELECT foreign_card.set_id AS foreign_set,
                   en_card.set_id AS en_set,
                   COUNT(*) AS match_count
            FROM cards foreign_card
            JOIN cards en_card ON foreign_card.eng_name = en_card.name
                AND foreign_card.collector_number = en_card.collector_number
                AND en_card.language = 'en'
            WHERE foreign_card.language = ?
                AND foreign_card.eng_name != ''
                AND foreign_card.collector_number IS NOT NULL
            GROUP BY foreign_card.set_id, en_card.set_id
            ORDER BY foreign_card.set_id, match_count DESC
        """, (lang,)).fetchall()

        # For each foreign set, take the EN set with most matches
        best_match: dict[str, tuple[str, int]] = {}
        for foreign_set, en_set, match_count in rows:
            if foreign_set not in best_match:
                best_match[foreign_set] = (en_set, match_count)

        # Look up cm_expansion_id for the matched EN sets
        for foreign_set, (en_set, match_count) in best_match.items():
            if match_count < 5:
                continue

            row = conn.execute(
                "SELECT cm_expansion_id FROM sets WHERE set_id = ? AND language = 'en'",
                (en_set,),
            ).fetchone()

            if row and row[0]:
                conn.execute(
                    "UPDATE sets SET cm_expansion_id = ? WHERE set_id = ? AND language = ?",
                    (row[0], foreign_set, lang),
                )
                updated += 1

    conn.commit()
    return updated


def main():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Ensure cm_expansion_id column exists
    try:
        conn.execute("ALTER TABLE sets ADD COLUMN cm_expansion_id INTEGER DEFAULT NULL")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Step 1: EN sets
    en_count = populate_en_set_expansion_ids(conn)
    print(f"EN sets updated with cm_expansion_id: {en_count}")

    # Step 2: JP/TW sets
    jptw_count = populate_jp_tw_set_expansion_ids(conn)
    print(f"JP/TW sets mapped via card matching: {jptw_count}")

    # Stats
    for lang in ("en", "ja", "zh-tw"):
        total = conn.execute(
            "SELECT COUNT(*) FROM sets WHERE language = ?", (lang,)
        ).fetchone()[0]
        with_exp = conn.execute(
            "SELECT COUNT(*) FROM sets WHERE language = ? AND cm_expansion_id IS NOT NULL",
            (lang,),
        ).fetchone()[0]
        print(f"  {lang}: {with_exp}/{total} sets have cm_expansion_id")

    conn.close()


if __name__ == "__main__":
    main()
