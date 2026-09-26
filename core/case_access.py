"""Case-level membership checks and source-grounded reference operations."""

from __future__ import annotations

from fastapi import HTTPException

from core.audit import log_action
from core.config import validate_case_id
from core.db import fetch_all, fetch_one, get_connection

CASE_REFERENCE_CONTEXT = "Potentially relevant information exists in another case."


def user_can_access_case(fir_id: str, user: dict, permission: str = "view") -> bool:
    try:
        validate_case_id(fir_id)
    except ValueError:
        return False
    if user.get("role") == "Admin":
        return True
    user_id = user.get("id")
    if user_id is None:
        return False
    membership = fetch_one(
        """SELECT can_view, can_upload, active
           FROM case_memberships
           WHERE fir_id = ? AND user_id = ?""",
        (fir_id, user_id),
    )
    if not membership or not membership["active"]:
        return False
    if permission == "view":
        return bool(membership["can_view"])
    if permission == "upload":
        return bool(membership["can_upload"])
    return False


def require_case_access(fir_id: str, user: dict, permission: str = "view") -> None:
    if not user_can_access_case(fir_id, user, permission):
        log_action(
            user.get("username", "UNKNOWN"),
            "CASE_ACCESS_DENIED",
            target=fir_id,
            details=f"permission={permission}",
        )
        raise HTTPException(status_code=403, detail="Case access denied")


def accessible_case_ids(user: dict) -> set[str]:
    if user.get("role") == "Admin":
        return {row["fir_id"] for row in fetch_all("SELECT fir_id FROM cases")}
    user_id = user.get("id")
    if user_id is None:
        return set()
    return {
        row["fir_id"]
        for row in fetch_all(
            "SELECT fir_id FROM case_memberships WHERE user_id = ? AND active = 1 AND can_view = 1",
            (user_id,),
        )
    }


def assign_case_member(
    fir_id: str,
    user_id: int,
    role: str,
    added_by: int | None,
) -> None:
    validate_case_id(fir_id)
    if role not in {"handler", "investigator"}:
        raise ValueError("role must be handler or investigator")
    if fetch_one("SELECT 1 FROM cases WHERE fir_id = ?", (fir_id,)) is None:
        raise ValueError("Case does not exist")
    if fetch_one("SELECT 1 FROM users WHERE id = ? AND is_active = 1", (user_id,)) is None:
        raise ValueError("Active user does not exist")
    can_upload = int(role == "handler")
    actor_username = _username_for_audit(added_by)
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO case_memberships
                   (fir_id, user_id, role, can_view, can_upload, active, added_by)
               VALUES (?, ?, ?, 1, ?, 1, ?)
               ON CONFLICT(fir_id, user_id) DO UPDATE SET
                   role = excluded.role,
                   can_view = 1,
                   can_upload = excluded.can_upload,
                   active = 1,
                   added_by = excluded.added_by""",
            (fir_id, user_id, role, can_upload, added_by),
        )
        log_action(
            actor_username,
            "CASE_MEMBER_ASSIGNED",
            target=fir_id,
            details=f"actor_user_id={added_by or 'unavailable'};user_id={user_id};role={role}",
            connection=conn,
        )


def _username_for_audit(user_id: int | None) -> str:
    if user_id is None:
        return "SYSTEM"
    user = fetch_one("SELECT username FROM users WHERE id = ?", (user_id,))
    return user["username"] if user else "SYSTEM"


def is_case_handler(fir_id: str, user: dict) -> bool:
    if user.get("role") == "Admin":
        return True
    user_id = user.get("id")
    if user_id is None:
        return False
    return fetch_one(
        """SELECT 1 FROM case_memberships
           WHERE fir_id = ? AND user_id = ? AND role = 'handler' AND active = 1""",
        (fir_id, user_id),
    ) is not None


def record_related_fir_reference(
    source_fir_id: str,
    referenced_fir_id: str,
    username: str = "SYSTEM",
    actor_user_id: int | None = None,
) -> bool:
    """Index an existing FIR Related_FIR_ID without copying source-case content."""
    validate_case_id(source_fir_id)
    validate_case_id(referenced_fir_id)
    if source_fir_id == referenced_fir_id:
        return False
    actor_username = username
    with get_connection() as conn:
        if conn.execute("SELECT 1 FROM cases WHERE fir_id = ?", (source_fir_id,)).fetchone() is None:
            return False
        if conn.execute("SELECT 1 FROM cases WHERE fir_id = ?", (referenced_fir_id,)).fetchone() is None:
            return False
        existing = conn.execute(
            """SELECT 1 FROM case_references
               WHERE source_fir_id = ? AND referenced_fir_id = ?
                 AND reference_type = 'related_fir'""",
            (source_fir_id, referenced_fir_id),
        ).fetchone()
        if existing:
            return False
        cursor = conn.execute(
            """INSERT INTO case_references
                   (source_fir_id, referenced_fir_id, reference_type, provenance, context)
               VALUES (?, ?, 'related_fir', 'FIR CSV Related_FIR_ID', ?)""",
            (source_fir_id, referenced_fir_id, CASE_REFERENCE_CONTEXT),
        )
        log_action(
            actor_username,
            "CASE_REFERENCE_CREATE",
            target=f"{source_fir_id}:{cursor.lastrowid}",
            details=(
                f"actor_user_id={actor_user_id or 'unavailable'};"
                f"source_fir_id={source_fir_id};related_fir_id={referenced_fir_id};"
                "reference_type=related_fir"
            ),
            connection=conn,
        )
    return True
