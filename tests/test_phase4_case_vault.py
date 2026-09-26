import asyncio
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.datastructures import UploadFile

from api.routers import case_vault
from core import config, db
from core.case_access import (
    assign_case_member,
    record_related_fir_reference,
    require_case_access,
    user_can_access_case,
)
from core.case_manager import create_case


class CaseVaultTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "cipher-test.db"
        self.db_patch = patch.object(db, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.cases_patch = patch.object(config, "CASES_DIR", self.root / "cases")
        self.cases_patch.start()
        db.init_db()

        self.handler_id = self._create_user("handler")
        self.requester_id = self._create_user("requester")
        self.other_id = self._create_user("other")
        self.handler = {"id": self.handler_id, "username": "handler", "role": "Field Investigator"}
        self.requester = {"id": self.requester_id, "username": "requester", "role": "Field Investigator"}
        self.other = {"id": self.other_id, "username": "other", "role": "Field Investigator"}
        self.admin = {"id": self.handler_id, "username": "handler", "role": "Admin"}

        create_case("FIR-2026-10001", {"district": "North"})
        create_case("FIR-2026-10002", {"district": "South"})
        assign_case_member("FIR-2026-10001", self.handler_id, "handler", self.handler_id)
        assign_case_member("FIR-2026-10002", self.requester_id, "investigator", self.requester_id)
        record_related_fir_reference("FIR-2026-10001", "FIR-2026-10002")

    def tearDown(self):
        self.cases_patch.stop()
        self.db_patch.stop()
        self.tempdir.cleanup()

    @staticmethod
    def _create_user(username):
        return db.execute(
            """INSERT INTO users (username, password_hash, role)
               VALUES (?, 'test-hash', 'Field Investigator')""",
            (username,),
        )

    def _add_document(self, fir_id="FIR-2026-10001", name="record.pdf", path="documents/original/record.pdf"):
        target = config.case_folder(fir_id) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF-1.7 test")
        return db.execute(
            """INSERT INTO case_documents
                   (fir_id, file_name, file_path, file_type, uploaded_by, sha256, size_bytes)
               VALUES (?, ?, ?, 'pdf', 'handler', 'digest', 13)""",
            (fir_id, name, path),
        )

    def test_case_ids_reject_path_traversal_and_case_access_is_membership_scoped(self):
        with self.assertRaises(ValueError):
            config.case_folder("../outside")
        self.assertTrue(user_can_access_case("FIR-2026-10001", self.handler))
        self.assertFalse(user_can_access_case("FIR-2026-10001", self.requester))
        with self.assertRaises(HTTPException) as error:
            require_case_access("FIR-2026-10001", self.requester)
        self.assertEqual(error.exception.status_code, 403)
        self.assertTrue(user_can_access_case("FIR-2026-10001", self.admin))

    def test_related_fir_reference_is_minimal_and_does_not_add_entities(self):
        before_entities = db.fetch_all("SELECT * FROM case_entities")
        response = case_vault.list_case_references("FIR-2026-10002", self.requester)
        self.assertEqual(len(response["references"]), 1)
        reference = response["references"][0]
        self.assertEqual(reference["related_case_id"], "FIR-2026-10001")
        self.assertEqual(
            set(reference),
            {"reference_id", "related_case_id", "reference_type", "provenance", "context"},
        )
        self.assertEqual(db.fetch_all("SELECT * FROM case_entities"), before_entities)
        self.assertFalse(record_related_fir_reference("FIR-2026-10001", "FIR-2026-10002"))

    def test_upload_uses_generated_filename_hashes_content_and_keeps_file_out_of_static(self):
        upload = UploadFile(filename="C:\\private\\original.pdf", file=BytesIO(b"%PDF-1.7 protected"))
        response = asyncio.run(
            case_vault.upload_case_document(
                "FIR-2026-10001",
                file=upload,
                document_type="FIR scan",
                source="collected record",
                user=self.handler,
            )
        )
        stored = db.fetch_one("SELECT * FROM case_documents WHERE id = ?", (response["id"],))
        path = config.case_folder(stored["fir_id"]) / stored["file_path"]
        self.assertNotEqual(stored["file_name"], path.name)
        self.assertEqual(stored["ocr_status"], "unavailable")
        self.assertEqual(len(stored["sha256"]), 64)
        self.assertTrue(path.is_file())
        self.assertNotIn("static", path.parts)
        self.assertTrue(path.resolve().is_relative_to(config.case_folder(stored["fir_id"]).resolve()))

    def test_invalid_upload_type_is_rejected_before_storage(self):
        upload = UploadFile(filename="payload.pdf", file=BytesIO(b"not a PDF"))
        with self.assertRaises(HTTPException) as error:
            asyncio.run(
                case_vault.upload_case_document(
                    "FIR-2026-10001", file=upload, document_type="", source="", user=self.handler
                )
            )
        self.assertEqual(error.exception.status_code, 415)
        self.assertEqual(db.fetch_all("SELECT * FROM case_documents"), [])

    def test_unrelated_investigator_cannot_list_or_download_protected_documents(self):
        document_id = self._add_document()
        with self.assertRaises(HTTPException) as list_error:
            case_vault.list_case_documents("FIR-2026-10001", self.other)
        self.assertEqual(list_error.exception.status_code, 403)
        with self.assertRaises(HTTPException) as download_error:
            case_vault.download_case_document(
                "FIR-2026-10001", document_id, self.other
            )
        self.assertEqual(download_error.exception.status_code, 403)

    def test_access_request_approval_scope_revoke_and_expiry(self):
        document_id = self._add_document()
        request_response = case_vault.create_access_request(
            case_vault.AccessRequestBody(
                requesting_fir_id="FIR-2026-10002",
                source_fir_id="FIR-2026-10001",
                reason="Review the source record for this investigation",
            ),
            self.requester,
        )
        request_id = request_response["request_id"]

        with self.assertRaises(HTTPException) as self_approval:
            case_vault.decide_access_request(
                request_id,
                case_vault.AccessDecision(decision="approve", document_ids=[document_id]),
                {"id": self.requester_id, "username": "requester", "role": "Admin"},
            )
        self.assertEqual(self_approval.exception.status_code, 403)

        decision = case_vault.decide_access_request(
            request_id,
            case_vault.AccessDecision(decision="approve", document_ids=[document_id]),
            self.handler,
        )
        grant_id = decision["grant_id"]
        audit_events = db.fetch_all("SELECT target, details FROM audit_log")
        audit_text = repr(audit_events)
        self.assertNotIn(grant_id, audit_text)
        self.assertEqual(
            case_vault._grant_document_ids("FIR-2026-10001", self.requester),
            {document_id},
        )
        self.assertFalse(
            case_vault._can_read_document(
                "FIR-2026-10001",
                db.fetch_one("SELECT * FROM case_documents WHERE id = ?", (document_id,)),
                self.other,
            )
        )
        db.execute(
            """UPDATE case_memberships SET active = 0
               WHERE fir_id = 'FIR-2026-10002' AND user_id = ?""",
            (self.requester_id,),
        )
        self.assertEqual(case_vault._grant_document_ids("FIR-2026-10001", self.requester), set())
        db.execute(
            """UPDATE case_memberships SET active = 1
               WHERE fir_id = 'FIR-2026-10002' AND user_id = ?""",
            (self.requester_id,),
        )
        case_vault.revoke_access_grant(grant_id, self.handler)
        self.assertEqual(case_vault._grant_document_ids("FIR-2026-10001", self.requester), set())

        request2 = case_vault.create_access_request(
            case_vault.AccessRequestBody(
                requesting_fir_id="FIR-2026-10002",
                source_fir_id="FIR-2026-10001",
                reason="Need another source record for review",
            ),
            self.requester,
        )["request_id"]
        case_vault.decide_access_request(
            request2,
            case_vault.AccessDecision(decision="approve", document_ids=[document_id]),
            self.handler,
        )
        db.execute(
            "UPDATE case_access_grants SET expires_at = '2000-01-01T00:00:00+00:00' WHERE request_id = ?",
            (request2,),
        )
        self.assertEqual(case_vault._grant_document_ids("FIR-2026-10001", self.requester), set())
        self.assertIsNotNone(
            db.fetch_one("SELECT expired_at FROM case_access_grants WHERE request_id = ?", (request2,))["expired_at"]
        )

    def test_approval_must_choose_existing_documents(self):
        request_id = case_vault.create_access_request(
            case_vault.AccessRequestBody(
                requesting_fir_id="FIR-2026-10002",
                source_fir_id="FIR-2026-10001",
                reason="Need the source record for review",
            ),
            self.requester,
        )["request_id"]
        with self.assertRaises(HTTPException) as error:
            case_vault.decide_access_request(
                request_id,
                case_vault.AccessDecision(decision="approve", document_ids=[9999]),
                self.handler,
            )
        self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(
            db.fetch_one("SELECT status FROM case_access_requests WHERE id = ?", (request_id,))["status"],
            "PENDING",
        )

    def test_entity_and_reference_writes_roll_back_when_audit_fails(self):
        with patch("core.case_manager.log_action", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                from core.case_manager import add_case_entity
                add_case_entity(
                    "FIR-2026-10001",
                    "Sensitive record label",
                    "person",
                    username="handler",
                    actor_user_id=self.handler_id,
                )
        self.assertEqual(db.fetch_all("SELECT * FROM case_entities"), [])

        with patch("core.case_access.log_action", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                record_related_fir_reference(
                    "FIR-2026-10002",
                    "FIR-2026-10001",
                    username="handler",
                    actor_user_id=self.handler_id,
                )
        self.assertEqual(
            db.fetch_all(
                "SELECT * FROM case_references WHERE source_fir_id = 'FIR-2026-10002'"
            ),
            [],
        )

    def test_member_assignment_rolls_back_when_audit_fails(self):
        with patch("core.case_access.log_action", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                assign_case_member(
                    "FIR-2026-10001", self.other_id, "investigator", self.handler_id
                )
        self.assertIsNone(
            db.fetch_one(
                """SELECT 1 FROM case_memberships
                   WHERE fir_id = 'FIR-2026-10001' AND user_id = ?""",
                (self.other_id,),
            )
        )

    def test_document_and_access_request_writes_roll_back_on_audit_failure(self):
        upload = UploadFile(filename="record.pdf", file=BytesIO(b"%PDF-1.7 protected"))
        with patch("api.routers.case_vault.log_action", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                asyncio.run(
                    case_vault.upload_case_document(
                        "FIR-2026-10001", file=upload, document_type="", source="", user=self.handler
                    )
                )
        self.assertEqual(db.fetch_all("SELECT * FROM case_documents"), [])
        self.assertEqual(
            list(config.case_documents_original_dir("FIR-2026-10001").iterdir()),
            [],
        )

        with patch("api.routers.case_vault.log_action", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                case_vault.create_access_request(
                    case_vault.AccessRequestBody(
                        requesting_fir_id="FIR-2026-10002",
                        source_fir_id="FIR-2026-10001",
                        reason="Request source records for investigation",
                    ),
                    self.requester,
                )
        self.assertEqual(db.fetch_all("SELECT * FROM case_access_requests"), [])

    def test_document_database_failure_removes_only_its_staged_upload(self):
        upload = UploadFile(filename="record.pdf", file=BytesIO(b"%PDF-1.7 protected"))
        with patch(
            "api.routers.case_vault.get_connection",
            side_effect=RuntimeError("database unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                asyncio.run(
                    case_vault.upload_case_document(
                        "FIR-2026-10001", file=upload, document_type="", source="", user=self.handler
                    )
                )
        self.assertEqual(db.fetch_all("SELECT * FROM case_documents"), [])
        self.assertEqual(
            list(config.case_documents_original_dir("FIR-2026-10001").iterdir()),
            [],
        )

    def test_document_filesystem_failure_rolls_back_document_metadata(self):
        upload = UploadFile(filename="record.pdf", file=BytesIO(b"%PDF-1.7 protected"))
        with patch("api.routers.case_vault.Path.rename", side_effect=OSError("filesystem unavailable")):
            with self.assertRaisesRegex(OSError, "filesystem unavailable"):
                asyncio.run(
                    case_vault.upload_case_document(
                        "FIR-2026-10001", file=upload, document_type="", source="", user=self.handler
                    )
                )
        self.assertEqual(db.fetch_all("SELECT * FROM case_documents"), [])
        self.assertEqual(
            list(config.case_documents_original_dir("FIR-2026-10001").iterdir()),
            [],
        )

    def test_approval_and_revocation_roll_back_when_audit_fails(self):
        document_id = self._add_document()
        request_id = case_vault.create_access_request(
            case_vault.AccessRequestBody(
                requesting_fir_id="FIR-2026-10002",
                source_fir_id="FIR-2026-10001",
                reason="Request source records for investigation",
            ),
            self.requester,
        )["request_id"]
        with patch("api.routers.case_vault.log_action", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                case_vault.decide_access_request(
                    request_id,
                    case_vault.AccessDecision(decision="approve", document_ids=[document_id]),
                    self.handler,
                )
        self.assertEqual(
            db.fetch_one(
                "SELECT status FROM case_access_requests WHERE id = ?", (request_id,)
            )["status"],
            "PENDING",
        )
        self.assertIsNone(
            db.fetch_one("SELECT 1 FROM case_access_grants WHERE request_id = ?", (request_id,))
        )

        case_vault.decide_access_request(
            request_id,
            case_vault.AccessDecision(decision="approve", document_ids=[document_id]),
            self.handler,
        )
        grant = db.fetch_one(
            "SELECT * FROM case_access_grants WHERE request_id = ?", (request_id,)
        )
        with patch("api.routers.case_vault.log_action", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                case_vault.revoke_access_grant(grant["id"], self.handler)
        self.assertIsNone(
            db.fetch_one(
                "SELECT revoked_at FROM case_access_grants WHERE id = ?", (grant["id"],)
            )["revoked_at"]
        )
        self.assertEqual(
            db.fetch_one(
                "SELECT status FROM case_access_requests WHERE id = ?", (request_id,)
            )["status"],
            "APPROVED",
        )


if __name__ == "__main__":
    unittest.main()
