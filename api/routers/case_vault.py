"""Authenticated case registration, protected documents, and access requests."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.security import get_current_user, require_admin
from core.audit import log_action
from core.case_access import (
    assign_case_member,
    is_case_handler,
    require_case_access,
    user_can_access_case,
)
from core.case_manager import case_exists, create_case
from core.config import (
    ACCESS_GRANT_LIFETIME_MINUTES,
    ACCESS_REQUEST_LIFETIME_DAYS,
    ALLOWED_UPLOAD_EXTENSIONS,
    MAX_UPLOAD_SIZE_MB,
    case_documents_original_dir,
    case_folder,
    validate_case_id,
)
from core.db import execute, fetch_all, fetch_one, get_connection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["case vault"])

MAX_UPLOAD_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024


class CaseRegistration(BaseModel):
    fir_id: str = Field(min_length=1, max_length=64)
    crime_type: str | None = None
    district: str | None = None
    fir_date: str | None = None
    status: str = "Open"


class MemberAssignment(BaseModel):
    user_id: int
    role: Literal["handler", "investigator"] = "investigator"


class AccessRequestBody(BaseModel):
    requesting_fir_id: str
    source_fir_id: str
    requested_scope: Literal["documents"] = "documents"
    reason: str = Field(min_length=5, max_length=2000)


class AccessDecision(BaseModel):
    decision: Literal["approve", "reject"]
    document_ids: list[int] = Field(default_factory=list, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


def _username(user: dict) -> str:
    return user.get("username") or "UNKNOWN"


def _document_path(fir_id: str, relative_path: str) -> Path:
    root = case_folder(fir_id).resolve()
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Document not found") from error
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")
    return path


def _safe_original_directory(fir_id: str) -> Path:
    root = case_folder(fir_id).resolve()
    directory = case_documents_original_dir(fir_id).resolve()
    try:
        directory.relative_to(root)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Invalid case storage path") from error
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _validate_file(path: Path, extension: str) -> None:
    with path.open("rb") as uploaded:
        header = uploaded.read(16)
    if extension == ".pdf" and not header.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="File content does not match PDF type")
    if extension in {".jpg", ".jpeg"} and not header.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=415, detail="File content does not match JPEG type")
    if extension == ".png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=415, detail="File content does not match PNG type")
    if extension == ".txt":
        content = path.read_bytes()
        if b"\x00" in content:
            raise HTTPException(status_code=415, detail="Text files cannot contain NUL bytes")
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise HTTPException(status_code=415, detail="Text files must be UTF-8") from error
    if extension == ".docx":
        try:
            with zipfile.ZipFile(path) as archive:
                if "word/document.xml" not in archive.namelist():
                    raise HTTPException(status_code=415, detail="Invalid DOCX document")
        except zipfile.BadZipFile as error:
            raise HTTPException(status_code=415, detail="Invalid DOCX document") from error


def _grant_document_ids(fir_id: str, user: dict) -> set[int]:
    rows = fetch_all(
        """SELECT g.id, g.scope_json, g.expires_at, g.expired_at
           FROM case_access_grants g
           JOIN case_access_requests r ON r.id = g.request_id
           JOIN case_memberships m
             ON m.fir_id = r.requesting_fir_id
            AND m.user_id = g.requester_user_id
            AND m.active = 1
            AND m.can_view = 1
           WHERE g.source_fir_id = ? AND g.requester_user_id = ?
             AND g.revoked_at IS NULL""",
        (fir_id, user["id"]),
    )
    allowed: set[int] = set()
    now = datetime.now(timezone.utc)
    for grant in rows:
        expires_at = datetime.fromisoformat(grant["expires_at"])
        if expires_at <= now:
            if not grant.get("expired_at"):
                timestamp = now.isoformat()
                execute(
                    "UPDATE case_access_grants SET expired_at = ? WHERE id = ? AND expired_at IS NULL",
                    (timestamp, grant["id"]),
                )
                log_action(
                    _username(user),
                    "CASE_ACCESS_GRANT_EXPIRED",
                    target=grant["id"],
                    details=f"source_fir_id={fir_id}",
                )
            continue
        scope = json.loads(grant["scope_json"])
        allowed.update(int(doc_id) for doc_id in scope.get("document_ids", []))
    return allowed


def _can_read_document(fir_id: str, document: dict, user: dict) -> bool:
    if user_can_access_case(fir_id, user):
        return True
    return document["id"] in _grant_document_ids(fir_id, user)


@router.post("/cases", status_code=201)
def register_case(body: CaseRegistration, user: dict = Depends(get_current_user)):
    try:
        validate_case_id(body.fir_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if case_exists(body.fir_id):
        raise HTTPException(status_code=409, detail="Case already exists")
    fields = body.dict(exclude={"fir_id"})
    try:
        created = create_case(
            body.fir_id,
            fields,
            username=_username(user),
            handler_user_id=user["id"],
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not created:
        raise HTTPException(status_code=409, detail="Case already exists")
    log_action(_username(user), "CASE_HANDLER_ASSIGNED", target=body.fir_id)
    return {"fir_id": body.fir_id, "status": "created"}


@router.post("/cases/{fir_id}/members", status_code=201)
def add_case_member(
    fir_id: str,
    body: MemberAssignment,
    user: dict = Depends(require_admin),
):
    try:
        assign_case_member(fir_id, body.user_id, body.role, user["id"])
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    log_action(
        _username(user),
        "CASE_MEMBER_ASSIGNED",
        target=fir_id,
        details=f"user_id={body.user_id};role={body.role}",
    )
    return {"fir_id": fir_id, "user_id": body.user_id, "role": body.role}


@router.post("/cases/{fir_id}/documents", status_code=201)
async def upload_case_document(
    fir_id: str,
    file: UploadFile = File(...),
    document_type: str = Form(default=""),
    source: str = Form(default=""),
    user: dict = Depends(get_current_user),
):
    try:
        require_case_access(fir_id, user, "upload")
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    supplied_name = (file.filename or "").replace("\\", "/").split("/")[-1]
    supplied_name = "".join(
        character for character in supplied_name if ord(character) >= 32 and ord(character) != 127
    ).strip()
    if not supplied_name:
        supplied_name = "uploaded-document"
    extension = Path(supplied_name).suffix.lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported document type")

    destination_dir = _safe_original_directory(fir_id)
    token = uuid.uuid4().hex
    temp_path = destination_dir / f".upload-{token}.tmp"
    storage_name = f"{token}{extension}"
    final_path = destination_dir / storage_name
    digest = hashlib.sha256()
    size = 0
    try:
        with temp_path.open("xb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_SIZE:
                    raise HTTPException(status_code=413, detail="Document exceeds the upload size limit")
                digest.update(chunk)
                target.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="Empty documents are not accepted")
        _validate_file(temp_path, extension)
        temp_path.replace(final_path)
        relative_path = final_path.relative_to(case_folder(fir_id)).as_posix()
        document_id = execute(
            """INSERT INTO case_documents
                   (fir_id, file_name, file_path, file_type, uploaded_by,
                    ocr_status, size_bytes, sha256, source, document_type)
               VALUES (?, ?, ?, ?, ?, 'unavailable', ?, ?, ?, ?)""",
            (
                fir_id,
                supplied_name[:255],
                relative_path,
                extension.lstrip("."),
                _username(user),
                size,
                digest.hexdigest(),
                source[:500],
                document_type[:100],
            ),
        )
    except Exception:
        temp_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    log_action(
        _username(user),
        "CASE_DOCUMENT_UPLOAD",
        target=f"{fir_id}:{document_id}",
        details=f"size_bytes={size};sha256={digest.hexdigest()}",
    )
    return {
        "id": document_id,
        "file_name": supplied_name[:255],
        "file_type": extension.lstrip("."),
        "size_bytes": size,
        "sha256": digest.hexdigest(),
        "ocr_status": "unavailable",
    }


@router.get("/cases/{fir_id}/documents")
def list_case_documents(fir_id: str, user: dict = Depends(get_current_user)):
    try:
        validate_case_id(fir_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if user_can_access_case(fir_id, user):
        rows = fetch_all(
            """SELECT id, file_name, file_type, uploaded_by, uploaded_at,
                      ocr_status, size_bytes, sha256, source, document_type
               FROM case_documents WHERE fir_id = ? ORDER BY id DESC""",
            (fir_id,),
        )
        log_action(
            _username(user),
            "CASE_DOCUMENT_LIST",
            target=fir_id,
            details=f"document_count={len(rows)};access=membership",
        )
        return {
            "documents": rows,
            "can_upload": user_can_access_case(fir_id, user, "upload"),
        }
    allowed_ids = _grant_document_ids(fir_id, user)
    if not allowed_ids:
        raise HTTPException(status_code=403, detail="Case access denied")
    placeholders = ",".join("?" for _ in allowed_ids)
    rows = fetch_all(
        f"""SELECT id, file_name, file_type, uploaded_by, uploaded_at,
                   ocr_status, size_bytes, sha256, source, document_type
            FROM case_documents WHERE fir_id = ? AND id IN ({placeholders}) ORDER BY id DESC""",
        (fir_id, *sorted(allowed_ids)),
    )
    log_action(
        _username(user),
        "CASE_DOCUMENT_LIST",
        target=fir_id,
        details=f"document_count={len(rows)};access=scoped_grant",
    )
    return {"documents": rows, "can_upload": False}


@router.get("/cases/{fir_id}/documents/{document_id}")
def download_case_document(
    fir_id: str,
    document_id: int,
    user: dict = Depends(get_current_user),
):
    try:
        validate_case_id(fir_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    document = fetch_one(
        "SELECT * FROM case_documents WHERE id = ? AND fir_id = ?",
        (document_id, fir_id),
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not _can_read_document(fir_id, document, user):
        raise HTTPException(status_code=403, detail="Document access denied")
    path = _document_path(fir_id, document["file_path"])
    log_action(
        _username(user),
        "CASE_DOCUMENT_ACCESS",
        target=f"{fir_id}:{document_id}",
    )
    return FileResponse(
        path,
        filename=document["file_name"],
        media_type="application/octet-stream",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/cases/{fir_id}/references")
def list_case_references(fir_id: str, user: dict = Depends(get_current_user)):
    require_case_access(fir_id, user)
    references = fetch_all(
        """SELECT id, source_fir_id, referenced_fir_id, reference_type,
                  provenance, context, created_at
           FROM case_references
           WHERE source_fir_id = ? OR referenced_fir_id = ?
           ORDER BY id""",
        (fir_id, fir_id),
    )
    return {
        "references": [
            {
                "reference_id": row["id"],
                "related_case_id": (
                    row["referenced_fir_id"]
                    if row["source_fir_id"] == fir_id
                    else row["source_fir_id"]
                ),
                "reference_type": row["reference_type"],
                "provenance": row["provenance"],
                "context": row["context"],
            }
            for row in references
        ]
    }


@router.post("/case-access/requests", status_code=201)
def create_access_request(
    body: AccessRequestBody,
    user: dict = Depends(get_current_user),
):
    for case_id in (body.requesting_fir_id, body.source_fir_id):
        try:
            validate_case_id(case_id)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    if body.requesting_fir_id == body.source_fir_id:
        raise HTTPException(status_code=422, detail="Cases must be different")
    require_case_access(body.requesting_fir_id, user)
    if user_can_access_case(body.source_fir_id, user):
        raise HTTPException(status_code=409, detail="You already have access to the source case")
    reference = fetch_one(
        """SELECT 1 FROM case_references
           WHERE (source_fir_id = ? AND referenced_fir_id = ?)
              OR (source_fir_id = ? AND referenced_fir_id = ?)""",
        (
            body.requesting_fir_id,
            body.source_fir_id,
            body.source_fir_id,
            body.requesting_fir_id,
        ),
    )
    if reference is None:
        raise HTTPException(status_code=404, detail="No case reference links these cases")

    request_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=ACCESS_REQUEST_LIFETIME_DAYS)
    execute(
        """INSERT INTO case_access_requests
               (id, requester_user_id, requesting_fir_id, source_fir_id,
                requested_scope, reason, status, created_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)""",
        (
            request_id,
            user["id"],
            body.requesting_fir_id,
            body.source_fir_id,
            json.dumps({"type": body.requested_scope}),
            body.reason,
            now.isoformat(),
            expires.isoformat(),
        ),
    )
    log_action(
        _username(user),
        "CASE_ACCESS_REQUEST",
        target=request_id,
        details=f"requesting_fir_id={body.requesting_fir_id};source_fir_id={body.source_fir_id}",
    )
    return {"request_id": request_id, "status": "PENDING", "expires_at": expires.isoformat()}


def _expire_pending_requests(rows: list[dict], actor: str) -> None:
    now = datetime.now(timezone.utc)
    for row in rows:
        if row["status"] == "PENDING" and datetime.fromisoformat(row["expires_at"]) <= now:
            execute(
                "UPDATE case_access_requests SET status = 'EXPIRED' WHERE id = ? AND status = 'PENDING'",
                (row["id"],),
            )
            log_action(actor, "CASE_ACCESS_REQUEST_EXPIRED", target=row["id"])
            row["status"] = "EXPIRED"


@router.get("/case-access/requests")
def list_access_requests(
    role: Literal["inbox", "outbox"] = "outbox",
    user: dict = Depends(get_current_user),
):
    if role == "outbox":
        rows = fetch_all(
            """SELECT r.id, r.requester_user_id, r.requesting_fir_id, r.source_fir_id,
                      r.requested_scope, r.status, r.reason, r.created_at, r.expires_at,
                      g.id AS grant_id, g.expires_at AS grant_expires_at,
                      g.revoked_at AS grant_revoked_at, g.expired_at AS grant_expired_at
               FROM case_access_requests r
               LEFT JOIN case_access_grants g ON g.request_id = r.id
               WHERE r.requester_user_id = ?
               ORDER BY r.created_at DESC""",
            (user["id"],),
        )
    else:
        rows = fetch_all(
            """SELECT r.id, r.requester_user_id, r.requesting_fir_id, r.source_fir_id,
                  r.requested_scope, r.status, r.reason, r.created_at, r.expires_at,
                  g.id AS grant_id, g.expires_at AS grant_expires_at,
                  g.revoked_at AS grant_revoked_at, g.expired_at AS grant_expired_at
               FROM case_access_requests r
               JOIN case_memberships m ON m.fir_id = r.source_fir_id
               LEFT JOIN case_access_grants g ON g.request_id = r.id
               WHERE m.user_id = ? AND m.role = 'handler' AND m.active = 1
               ORDER BY r.created_at DESC""",
            (user["id"],),
        )
        if user.get("role") == "Admin":
            rows = fetch_all(
                """SELECT r.id, r.requester_user_id, r.requesting_fir_id, r.source_fir_id,
                          r.requested_scope, r.status, r.reason, r.created_at, r.expires_at,
                          g.id AS grant_id, g.expires_at AS grant_expires_at,
                          g.revoked_at AS grant_revoked_at, g.expired_at AS grant_expired_at
                   FROM case_access_requests r
                   LEFT JOIN case_access_grants g ON g.request_id = r.id
                   ORDER BY r.created_at DESC"""
            )
        _expire_pending_requests(rows, _username(user))
        for row in rows:
            row["documents"] = (
                fetch_all(
                    """SELECT id, file_name, file_type, size_bytes, sha256, document_type
                       FROM case_documents WHERE fir_id = ? ORDER BY id DESC""",
                    (row["source_fir_id"],),
                )
                if row["status"] == "PENDING"
                else []
            )
    if role == "outbox":
        _expire_pending_requests(rows, _username(user))
    return {"requests": rows}


@router.post("/case-access/requests/{request_id}/decision")
def decide_access_request(
    request_id: str,
    body: AccessDecision,
    user: dict = Depends(get_current_user),
):
    request = fetch_one("SELECT * FROM case_access_requests WHERE id = ?", (request_id,))
    if request is None:
        raise HTTPException(status_code=404, detail="Access request not found")
    if not is_case_handler(request["source_fir_id"], user):
        raise HTTPException(status_code=403, detail="Source case handler access required")
    if request["requester_user_id"] == user.get("id"):
        raise HTTPException(status_code=403, detail="Requesters cannot approve their own requests")
    requester_membership = fetch_one(
        """SELECT 1 FROM case_memberships
           WHERE fir_id = ? AND user_id = ? AND active = 1 AND can_view = 1""",
        (request["requesting_fir_id"], request["requester_user_id"]),
    )
    if requester_membership is None:
        raise HTTPException(status_code=409, detail="Requester no longer has access to the requesting case")
    if request["status"] != "PENDING":
        raise HTTPException(status_code=409, detail="Request is no longer pending")
    now = datetime.now(timezone.utc)
    if datetime.fromisoformat(request["expires_at"]) <= now:
        execute(
            "UPDATE case_access_requests SET status = 'EXPIRED' WHERE id = ? AND status = 'PENDING'",
            (request_id,),
        )
        log_action(_username(user), "CASE_ACCESS_REQUEST_EXPIRED", target=request_id)
        raise HTTPException(status_code=410, detail="Access request has expired")

    grant_id = None
    with get_connection() as conn:
        cursor = conn.execute(
            """UPDATE case_access_requests
               SET status = ?, decision_user_id = ?, decision_at = ?, decision_notes = ?
               WHERE id = ? AND status = 'PENDING'""",
            (
                "APPROVED" if body.decision == "approve" else "REJECTED",
                user["id"],
                now.isoformat(),
                body.notes,
                request_id,
            ),
        )
        if cursor.rowcount != 1:
            raise HTTPException(status_code=409, detail="Request is no longer pending")
        if body.decision == "approve":
            requested = json.loads(request["requested_scope"])
            if requested.get("type") != "documents":
                raise HTTPException(status_code=422, detail="Unsupported access scope")
            available = {
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM case_documents WHERE fir_id = ?",
                    (request["source_fir_id"],),
                ).fetchall()
            }
            selected = set(body.document_ids)
            if not selected or not selected.issubset(available):
                raise HTTPException(
                    status_code=422,
                    detail="Approval must select one or more existing source-case documents",
                )
            grant_id = uuid.uuid4().hex
            expires = now + timedelta(minutes=ACCESS_GRANT_LIFETIME_MINUTES)
            conn.execute(
                """INSERT INTO case_access_grants
                       (id, request_id, requester_user_id, source_fir_id,
                        scope_json, issued_at, expires_at, approved_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    grant_id,
                    request_id,
                    request["requester_user_id"],
                    request["source_fir_id"],
                    json.dumps({"document_ids": sorted(selected)}),
                    now.isoformat(),
                    expires.isoformat(),
                    user["id"],
                ),
            )

    action = "CASE_ACCESS_APPROVED" if body.decision == "approve" else "CASE_ACCESS_REJECTED"
    log_action(
        _username(user),
        action,
        target=request_id,
        details=f"grant_id={grant_id or ''};notes={body.notes or ''}",
    )
    return {"request_id": request_id, "status": body.decision.upper(), "grant_id": grant_id}


@router.post("/case-access/grants/{grant_id}/revoke")
def revoke_access_grant(grant_id: str, user: dict = Depends(get_current_user)):
    grant = fetch_one("SELECT * FROM case_access_grants WHERE id = ?", (grant_id,))
    if grant is None:
        raise HTTPException(status_code=404, detail="Access grant not found")
    if not is_case_handler(grant["source_fir_id"], user):
        raise HTTPException(status_code=403, detail="Source case handler access required")
    if grant["revoked_at"]:
        raise HTTPException(status_code=409, detail="Access grant is already revoked")
    timestamp = datetime.now(timezone.utc).isoformat()
    execute(
        "UPDATE case_access_grants SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
        (timestamp, grant_id),
    )
    execute(
        """UPDATE case_access_requests SET status = 'REVOKED'
           WHERE id = ? AND status = 'APPROVED'""",
        (grant["request_id"],),
    )
    log_action(_username(user), "CASE_ACCESS_REVOKED", target=grant_id)
    return {"grant_id": grant_id, "status": "REVOKED"}
