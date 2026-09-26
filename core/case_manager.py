"""
CIPHER — Case Manager
Owns the lifecycle of a case: creating its on-disk folder structure,
its case_record.json, and its row in the `cases` table, plus attaching
entities to it in `case_entities`. Every other module (bulk importer,
upload/OCR flow, dashboard pages) should go through this file rather
than touching case folders or the `cases`/`case_entities` tables directly.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.audit import log_action
from core.config import (
    case_audit_log_path,
    case_documents_original_dir,
    case_documents_scans_dir,
    case_folder,
    case_notes_dir,
    case_ocr_text_dir,
    case_record_path,
    case_timeline_path,
)
from core.db import execute, fetch_all, fetch_one, get_connection

logger = logging.getLogger(__name__)

VALID_ENTITY_ROLES = {
    "complainant", "victim", "suspect", "associate",
    "witness", "vehicle", "account", "location",
}
VALID_CONFIDENCE_TIERS = {
    "observed_fact", "derived_signal", "ai_inference", "investigator_confirmed",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def case_exists(fir_id: str) -> bool:
    """True if this case already has a row in the `cases` table."""
    return fetch_one("SELECT 1 FROM cases WHERE fir_id = ?", (fir_id,)) is not None


def create_case_folders(fir_id: str) -> None:
    """Create the full on-disk folder structure for a case. Safe to call
    repeatedly — every mkdir is idempotent."""
    case_folder(fir_id).mkdir(parents=True, exist_ok=True)
    case_documents_original_dir(fir_id).mkdir(parents=True, exist_ok=True)
    case_documents_scans_dir(fir_id).mkdir(parents=True, exist_ok=True)
    case_ocr_text_dir(fir_id).mkdir(parents=True, exist_ok=True)
    case_notes_dir(fir_id).mkdir(parents=True, exist_ok=True)
    (case_folder(fir_id) / "evidence").mkdir(parents=True, exist_ok=True)
    (case_folder(fir_id) / "extracted").mkdir(parents=True, exist_ok=True)


def create_case(
    fir_id: str,
    fields: dict[str, Any],
    username: str = "SYSTEM",
    handler_user_id: int | None = None,
) -> bool:
    """
    Create a new case: folder structure, case_record.json, `cases` DB row.

    `fields` should carry whatever FIR columns are available (crime_type,
    district, status, fir_date, description, etc.) — only a subset is
    stored as dedicated DB columns; the full dict is kept in case_record.json.

    Idempotent: if the case already exists (by fir_id), this is a no-op
    and returns False rather than raising or duplicating anything — this
    matters for bulk import, which may be re-run.

    Returns True if a new case was created, False if it already existed.
    """
    if case_exists(fir_id):
        logger.info("Case %s already exists, skipping creation.", fir_id)
        return False

    case_folder(fir_id)
    if handler_user_id is not None and fetch_one(
        "SELECT 1 FROM users WHERE id = ? AND is_active = 1", (handler_user_id,)
    ) is None:
        raise ValueError("Active registering handler does not exist")
    create_case_folders(fir_id)
    folder_path = str(case_folder(fir_id))

    with get_connection() as conn:
        conn.execute(
            """INSERT INTO cases (fir_id, crime_type, district, status, fir_date, folder_path)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                fir_id,
                fields.get("crime_type") or fields.get("Crime_Type"),
                fields.get("district") or fields.get("District"),
                fields.get("status") or fields.get("Status") or "Open",
                fields.get("fir_date") or fields.get("FIR_Date"),
                folder_path,
            ),
        )
        if handler_user_id is not None:
            conn.execute(
                """INSERT INTO case_memberships
                       (fir_id, user_id, role, can_view, can_upload, active, added_by)
                   VALUES (?, ?, 'handler', 1, 1, 1, ?)""",
                (fir_id, handler_user_id, handler_user_id),
            )

    record = {
        "fir_id": fir_id,
        "fields": fields,
        "status": fields.get("status") or fields.get("Status") or "Open",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    case_record_path(fir_id).write_text(json.dumps(record, indent=2), encoding="utf-8")

    # Empty timeline and audit-log-per-case scaffolding, so downstream code
    # (OCR review, notes, etc.) can always assume these files exist.
    if not case_timeline_path(fir_id).exists():
        case_timeline_path(fir_id).write_text(json.dumps([], indent=2), encoding="utf-8")
    case_audit_log_path(fir_id).touch(exist_ok=True)

    log_action(username, "CASE_CREATE", target=fir_id, details=f"district={record['fields'].get('district') or record['fields'].get('District')}")
    logger.info("Case created: %s", fir_id)
    return True


def get_case(fir_id: str) -> dict[str, Any] | None:
    """Return the DB row + parsed case_record.json for a case, or None if
    it doesn't exist."""
    row = fetch_one("SELECT * FROM cases WHERE fir_id = ?", (fir_id,))
    if row is None:
        return None

    record: dict[str, Any] = {}
    record_path = case_record_path(fir_id)
    if record_path.exists():
        record = json.loads(record_path.read_text(encoding="utf-8"))

    return {**row, "record": record}


def list_cases(status: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
    """List cases from the DB, most recently created first."""
    query = "SELECT * FROM cases"
    params: list[Any] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return fetch_all(query, tuple(params))


def update_case_status(fir_id: str, new_status: str, username: str = "SYSTEM") -> None:
    """Update a case's status in both the DB and case_record.json."""
    if not case_exists(fir_id):
        raise ValueError(f"Case {fir_id} does not exist")

    execute(
        "UPDATE cases SET status = ?, updated_at = datetime('now') WHERE fir_id = ?",
        (new_status, fir_id),
    )

    record_path = case_record_path(fir_id)
    record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {}
    record["status"] = new_status
    record["updated_at"] = _now_iso()
    record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    log_action(username, "CASE_STATUS_UPDATE", target=fir_id, details=f"new_status={new_status}")
    logger.info("Case %s status updated to %s", fir_id, new_status)


def add_case_entity(
    fir_id: str,
    entity_label: str,
    entity_type: str,
    role: str | None = None,
    confidence_tier: str = "observed_fact",
    source: str | None = None,
    username: str = "SYSTEM",
) -> int:
    """
    Attach an entity to a case in case_entities. This is the link that
    makes a future case-scoped graph view possible: given a fir_id, query
    case_entities to get its seed nodes, then pull their neighbours from
    the global graph.

    Does not deduplicate — call sites (e.g. the bulk importer) are
    responsible for not re-adding the same entity+role twice per case if
    that matters for their use case.
    """
    if not case_exists(fir_id):
        raise ValueError(f"Case {fir_id} does not exist")
    if role is not None and role not in VALID_ENTITY_ROLES:
        raise ValueError(f"role must be one of {VALID_ENTITY_ROLES}, got {role!r}")
    if confidence_tier not in VALID_CONFIDENCE_TIERS:
        raise ValueError(f"confidence_tier must be one of {VALID_CONFIDENCE_TIERS}, got {confidence_tier!r}")

    row_id = execute(
        """INSERT INTO case_entities (fir_id, entity_label, entity_type, role, confidence_tier, source)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (fir_id, entity_label, entity_type, role, confidence_tier, source),
    )
    logger.debug("Entity attached to %s: %s (%s, role=%s)", fir_id, entity_label, entity_type, role)
    return row_id


def get_case_entities(fir_id: str) -> list[dict]:
    """All entities attached to a case, for building the case-scoped graph
    view or showing the case's entity list in the UI."""
    return fetch_all(
        "SELECT * FROM case_entities WHERE fir_id = ? ORDER BY added_at", (fir_id,)
    )


if __name__ == "__main__":
    import sys

    from core.db import init_db

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.path.insert(0, ".")

    init_db()

    created = create_case(
        "FIR-2026-99999",
        {
            "crime_type": "Theft",
            "district": "Test District",
            "status": "Open",
            "fir_date": "2026-01-01",
            "description": "Self-test case created by core/case_manager.py",
        },
        username="selftest",
    )
    print("Case created:" if created else "Case already existed, skipped:", "FIR-2026-99999")

    again = create_case("FIR-2026-99999", {"crime_type": "Theft"}, username="selftest")
    print("Re-running create_case is idempotent (should be False):", again)

    add_case_entity("FIR-2026-99999", "Test Suspect", "person", role="suspect", confidence_tier="observed_fact", username="selftest")
    add_case_entity("FIR-2026-99999", "9876543210", "phone", role="suspect", confidence_tier="observed_fact", username="selftest")

    case = get_case("FIR-2026-99999")
    print("\nCase record:")
    print(json.dumps(case, indent=2, default=str))

    print("\nEntities attached:")
    for e in get_case_entities("FIR-2026-99999"):
        print(f"  {e['entity_label']} ({e['entity_type']}, role={e['role']}, tier={e['confidence_tier']})")

    print("\nCase folders created at:", case_folder("FIR-2026-99999"))