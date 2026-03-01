"""
SQLite database for Pokemon card data.

Tables:
    sets              — one row per set (EN from TCGdex, JP from pokemon-card.com, TW from asia.pokemon-card.com)
    cards             — one row per card, multi-language (EN/JA/ZH-TW)
    prices            — CardMarket pricing (linked by cm_id_product)
    card_external_ids — marketplace ID mappings (PokeTrace, TCGPlayer, Pokemon-API)
    prices_external   — multi-source price snapshots (PokeTrace, Pokemon-API)
    enrichment_runs   — track enrichment script progress for resumability
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path("./data/cards.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sets (
    set_id              TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    series              TEXT DEFAULT '',
    abbreviation        TEXT DEFAULT '',
    card_count_official INTEGER DEFAULT 0,
    card_count_total    INTEGER DEFAULT 0,
    release_date        TEXT DEFAULT '',
    logo_url            TEXT DEFAULT '',
    language            TEXT DEFAULT 'en',
    cm_expansion_id     INTEGER DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_sets_name ON sets(name);
CREATE INDEX IF NOT EXISTS idx_sets_abbr ON sets(abbreviation);
CREATE INDEX IF NOT EXISTS idx_sets_lang ON sets(language);

CREATE TABLE IF NOT EXISTS cards (
    tcgdex_id        TEXT PRIMARY KEY,
    set_id           TEXT NOT NULL REFERENCES sets(set_id),
    local_id         TEXT NOT NULL,
    collector_number INTEGER DEFAULT NULL,
    set_total        INTEGER DEFAULT NULL,
    name             TEXT NOT NULL,
    name_normalized  TEXT DEFAULT '',
    eng_name         TEXT DEFAULT '',
    language         TEXT DEFAULT 'en',
    rarity           TEXT DEFAULT '',
    category         TEXT DEFAULT '',
    hp               INTEGER DEFAULT NULL,
    illustrator      TEXT DEFAULT '',
    image_url        TEXT DEFAULT '',
    image_local      TEXT DEFAULT '',
    cm_id_product    INTEGER DEFAULT NULL,
    cm_url_slug      TEXT DEFAULT '',
    fetched_at       TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_cards_number ON cards(collector_number);
CREATE INDEX IF NOT EXISTS idx_cards_set_number ON cards(set_id, collector_number);
CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name_normalized);
CREATE INDEX IF NOT EXISTS idx_cards_cm ON cards(cm_id_product);
CREATE INDEX IF NOT EXISTS idx_cards_lang ON cards(language);
CREATE INDEX IF NOT EXISTS idx_cards_lang_number ON cards(language, collector_number);
CREATE INDEX IF NOT EXISTS idx_cards_lang_total ON cards(language, collector_number, set_total);
CREATE INDEX IF NOT EXISTS idx_cards_lang_name ON cards(language, name_normalized);

CREATE TABLE IF NOT EXISTS prices (
    cm_id_product   INTEGER PRIMARY KEY,
    cm_name         TEXT DEFAULT '',
    cm_expansion_id INTEGER DEFAULT NULL,
    avg             REAL DEFAULT 0,
    low             REAL DEFAULT 0,
    trend           REAL DEFAULT 0,
    avg1            REAL DEFAULT NULL,
    avg7            REAL DEFAULT NULL,
    avg30           REAL DEFAULT NULL,
    foil_trend      REAL DEFAULT 0,
    foil_low        REAL DEFAULT 0,
    updated_at      TEXT DEFAULT ''
);

-- External marketplace ID mappings (PokeTrace, TCGPlayer, Pokemon-API)
CREATE TABLE IF NOT EXISTS card_external_ids (
    tcgdex_id        TEXT PRIMARY KEY REFERENCES cards(tcgdex_id),
    poketrace_id     TEXT,
    tcgplayer_id     INTEGER,
    pokemon_api_id   INTEGER,
    poketrace_set_slug TEXT DEFAULT '',
    matched_at       TEXT DEFAULT '',
    match_method     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ext_tcgplayer ON card_external_ids(tcgplayer_id);
CREATE INDEX IF NOT EXISTS idx_ext_poketrace ON card_external_ids(poketrace_id);

-- Multi-source price snapshots (daily snapshots from PokeTrace + Pokemon-API)
CREATE TABLE IF NOT EXISTS prices_external (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tcgdex_id       TEXT NOT NULL REFERENCES cards(tcgdex_id),
    source          TEXT NOT NULL,
    marketplace     TEXT NOT NULL,
    condition       TEXT NOT NULL,
    country         TEXT DEFAULT 'ALL',
    currency        TEXT NOT NULL,
    price_avg       REAL,
    price_low       REAL,
    price_high      REAL,
    price_trend     TEXT DEFAULT '',
    avg_1d          REAL,
    avg_7d          REAL,
    avg_30d         REAL,
    sale_count      INTEGER,
    confidence      TEXT DEFAULT '',
    snapshot_date   TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE(tcgdex_id, source, marketplace, condition, country, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_pe_card ON prices_external(tcgdex_id);
CREATE INDEX IF NOT EXISTS idx_pe_lookup ON prices_external(tcgdex_id, marketplace, condition);

-- Track enrichment script progress for resumability
CREATE TABLE IF NOT EXISTS enrichment_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    phase           TEXT NOT NULL,
    started_at      TEXT DEFAULT '',
    completed_at    TEXT DEFAULT '',
    last_offset     TEXT DEFAULT '',
    cards_processed INTEGER DEFAULT 0,
    cards_total     INTEGER,
    status          TEXT DEFAULT 'running'
);
"""

# Migration steps: (sql, can_fail)
# can_fail=True means "duplicate column" errors are expected
_MIGRATIONS: list[tuple[str, bool]] = [
    ("ALTER TABLE sets ADD COLUMN language TEXT DEFAULT 'en'", True),
    ("ALTER TABLE cards ADD COLUMN set_total INTEGER DEFAULT NULL", True),
    ("ALTER TABLE cards ADD COLUMN eng_name TEXT DEFAULT ''", True),
    ("ALTER TABLE cards ADD COLUMN language TEXT DEFAULT 'en'", True),
    ("CREATE INDEX IF NOT EXISTS idx_sets_lang ON sets(language)", False),
    ("CREATE INDEX IF NOT EXISTS idx_cards_lang ON cards(language)", False),
    ("CREATE INDEX IF NOT EXISTS idx_cards_lang_number ON cards(language, collector_number)", False),
    ("CREATE INDEX IF NOT EXISTS idx_cards_lang_total ON cards(language, collector_number, set_total)", False),
    ("CREATE INDEX IF NOT EXISTS idx_cards_lang_name ON cards(language, name_normalized)", False),
    ("ALTER TABLE sets ADD COLUMN cm_expansion_id INTEGER DEFAULT NULL", True),
    # Phase 2: External API enrichment columns
    ("ALTER TABLE cards ADD COLUMN tcgplayer_id INTEGER DEFAULT NULL", True),
    ("ALTER TABLE cards ADD COLUMN top_price_eur REAL DEFAULT NULL", True),
    ("ALTER TABLE cards ADD COLUMN top_price_usd REAL DEFAULT NULL", True),
    ("ALTER TABLE cards ADD COLUMN has_graded INTEGER DEFAULT 0", True),
    ("ALTER TABLE cards ADD COLUMN enriched_at TEXT DEFAULT ''", True),
]


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Get a database connection with WAL mode and row_factory."""
    path = str(db_path or DB_PATH)
    conn = sqlite3.connect(path, timeout=30)  # Wait up to 30s for locks
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")  # 30s busy timeout
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they don't exist."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def migrate_db(conn: sqlite3.Connection) -> None:
    """Apply migrations for existing databases (adds new columns safely)."""
    for sql, can_fail in _MIGRATIONS:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            if can_fail and "duplicate column" in str(e).lower():
                continue
            raise
    conn.commit()


def ensure_schema(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Get connection, create tables if needed, and apply migrations."""
    conn = get_connection(db_path)
    # First migrate (add new columns to existing tables)
    migrate_db(conn)
    # Then create tables + all indexes (safe for new DBs, indexes use IF NOT EXISTS)
    init_db(conn)
    return conn
