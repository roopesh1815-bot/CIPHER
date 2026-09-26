"""
CIPHER — Database Layer
SQLite schema and connection helpers. Every other core/ and pipeline/ module
that needs persistent storage goes through this file — no raw sqlite3 calls
anywhere else in the project.
"""

import sqlite3
import logging
from contextlib import contextmanager
from pathlib import Path

from core.config import DB_PATH

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('Field Investigator', 'Admin')),
    full_name     TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    is_active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL DEFAULT (datetime('now')),
    username      TEXT NOT NULL,
    action        TEXT NOT NULL,
    target        TEXT,
    details       TEXT,
    prev_hash     TEXT NOT NULL,
    entry_hash    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    fir_id        TEXT PRIMARY KEY,
    crime_type    TEXT,
    district      TEXT,
    status        TEXT,
    fir_date      TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    folder_path   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fir_id        TEXT NOT NULL REFERENCES cases(fir_id),
    file_name     TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    file_type     TEXT,
    uploaded_by   TEXT,
    uploaded_at   TEXT NOT NULL DEFAULT (datetime('now')),
    ocr_status    TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS case_entities (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    fir_id            TEXT NOT NULL REFERENCES cases(fir_id),
    entity_label      TEXT NOT NULL,
    entity_type       TEXT NOT NULL,
    role              TEXT,
    confidence_tier   TEXT NOT NULL CHECK (
        confidence_tier IN ('observed_fact', 'derived_signal', 'ai_inference', 'investigator_confirmed')
    ),
    source            TEXT,
    added_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_username ON audit_log(username);
CREATE INDEX IF NOT EXISTS idx_case_documents_fir ON case_documents(fir_id);
CREATE INDEX IF NOT EXISTS idx_case_entities_fir ON case_entities(fir_id);
"""


@contextmanager
def get_connection():
    """
    Context-managed SQLite connection with foreign keys enforced and
    row access by column name. Commits on success, rolls back on error.
    Usage:
        with get_connection() as conn:
            conn.execute("INSERT INTO ...", (...))
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Database operation failed, rolled back.")
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables/indexes if they don't already exist. Safe to call repeatedly."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
    logger.info(f"Database initialised at {DB_PATH}")


def fetch_all(query: str, params: tuple = ()) -> list[dict]:
    """Run a SELECT and return a list of dicts."""
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def fetch_one(query: str, params: tuple = ()) -> dict | None:
    """Run a SELECT expecting at most one row; return a dict or None."""
    with get_connection() as conn:
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None


def execute(query: str, params: tuple = ()) -> int:
    """Run an INSERT/UPDATE/DELETE. Returns lastrowid (useful for INSERTs)."""
    with get_connection() as conn:
        cursor = conn.execute(query, params)
        return cursor.lastrowid


if __name__ == "__main__":
    init_db()
    print(f"Database ready at: {DB_PATH}")
    tables = fetch_all("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    print("Tables created:")
    for t in tables:
        print(f"  - {t['name']}")