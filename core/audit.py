"""
CIPHER — Audit Log Layer
Hash-chained, tamper-evident audit trail. Every security-relevant action
(login, case create/update, document upload, entity confirm, etc.) should
go through log_action() rather than writing to audit_log directly.
"""

import hashlib
import logging
import sqlite3
from datetime import datetime, timezone

from core.db import fetch_one, fetch_all, execute

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64  # prev_hash for the very first entry in the chain


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_hash(prev_hash: str, timestamp: str, username: str,
                   action: str, target: str, details: str) -> str:
    """
    Deterministic SHA-256 over the entry's fields + the previous entry's hash.
    Field order here MUST stay fixed — changing it breaks verification of
    every chain created before the change.
    """
    payload = f"{prev_hash}|{timestamp}|{username}|{action}|{target or ''}|{details or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_last_hash(connection: sqlite3.Connection | None = None) -> str:
    """Returns the entry_hash of the most recent audit_log row, or GENESIS_HASH if empty."""
    if connection is not None:
        last = connection.execute(
            "SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return last["entry_hash"] if last else GENESIS_HASH
    last = fetch_one("SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1")
    return last["entry_hash"] if last else GENESIS_HASH


def log_action(
    username: str,
    action: str,
    target: str = "",
    details: str = "",
    connection: sqlite3.Connection | None = None,
) -> int:
    """
    Append a tamper-evident entry to the audit log.
    Returns the new row's id.

    Examples:
        log_action("admin", "LOGIN_SUCCESS", target="admin")
        log_action("admin", "CASE_CREATE", target="FIR-2026-0042", details="district=Chennai")
        log_action("admin", "ENTITY_CONFIRM", target="entity_id=1183", details="tier=investigator_confirmed")
    """
    timestamp = _now_iso()
    prev_hash = _get_last_hash(connection)
    entry_hash = _compute_hash(prev_hash, timestamp, username, action, target, details)

    if connection is not None:
        cursor = connection.execute(
            """INSERT INTO audit_log (timestamp, username, action, target, details, prev_hash, entry_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (timestamp, username, action, target, details, prev_hash, entry_hash),
        )
        row_id = cursor.lastrowid
        logger.info(f"Audit: [{action}] by {username} -> {target}")
        return row_id

    row_id = execute(
        """INSERT INTO audit_log (timestamp, username, action, target, details, prev_hash, entry_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (timestamp, username, action, target, details, prev_hash, entry_hash),
    )
    logger.info(f"Audit: [{action}] by {username} -> {target}")
    return row_id


def verify_chain() -> dict:
    """
    Walk the entire audit_log and confirm every entry's hash matches what
    it should be given its own fields + the previous row's stored hash.

    Returns:
        {
          "valid": bool,
          "entries_checked": int,
          "first_break_id": int | None,   # id of the first tampered/broken row, if any
        }
    """
    rows = fetch_all("SELECT * FROM audit_log ORDER BY id ASC")
    expected_prev = GENESIS_HASH

    for row in rows:
        recomputed = _compute_hash(
            expected_prev, row["timestamp"], row["username"],
            row["action"], row["target"], row["details"],
        )
        if row["prev_hash"] != expected_prev or row["entry_hash"] != recomputed:
            return {"valid": False, "entries_checked": len(rows), "first_break_id": row["id"]}
        expected_prev = row["entry_hash"]

    return {"valid": True, "entries_checked": len(rows), "first_break_id": None}


def get_audit_trail(username: str = None, action: str = None, limit: int = 100) -> list[dict]:
    """Filtered, most-recent-first view of the log for the UI (not for verification)."""
    query = "SELECT * FROM audit_log WHERE 1=1"
    params = []
    if username:
        query += " AND username = ?"
        params.append(username)
    if action:
        query += " AND action = ?"
        params.append(action)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return fetch_all(query, tuple(params))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")

    log_action("admin", "LOGIN_SUCCESS", target="admin")
    log_action("admin", "CASE_CREATE", target="FIR-2026-0042", details="district=Chennai")
    log_action("admin", "ENTITY_CONFIRM", target="entity_id=1183", details="tier=investigator_confirmed")

    result = verify_chain()
    print(f"Chain verification: {result}")

    print("\nRecent entries:")
    for entry in get_audit_trail(limit=5):
        print(f"  [{entry['id']}] {entry['timestamp']} {entry['username']} -> {entry['action']} ({entry['target']})")

    # --- Tamper test: prove the chain catches it ---
    print("\nSimulating tamper (editing details on row id=1)...")
    execute("UPDATE audit_log SET details = 'HACKED' WHERE id = 1")
    result_after_tamper = verify_chain()
    print(f"Chain verification after tamper: {result_after_tamper}")