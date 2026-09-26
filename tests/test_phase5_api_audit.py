import unittest
import asyncio
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from api import main
from api.routers import alerts, auth
from api.security import COOKIE_NAME, get_current_user
from core import config, db
from core.audit import get_audit_trail, verify_chain
from core.case_access import assign_case_member, record_related_fir_reference
from core.case_manager import add_case_entity, create_case, update_case_status


def request_app(path: str):
    messages = []
    sent_request = False

    async def receive():
        nonlocal sent_request
        if sent_request:
            return {"type": "http.disconnect"}
        sent_request = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
    }
    asyncio.run(main.app(scope, receive, send))
    return next(message["status"] for message in messages if message["type"] == "http.response.start")


class Phase5ApiAuthTests(unittest.TestCase):
    def test_global_investigation_endpoints_require_authentication(self):
        paths = (
            "/api/alerts",
            "/api/alerts/ANOM-1",
            "/api/hidden-links",
            "/api/hidden-links/HL-1",
            "/api/communities",
            "/api/communities/1",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(request_app(path), 401)

    def test_each_auth_and_alert_route_is_registered_once(self):
        included_routers = [
            route.original_router
            for route in main.app.routes
            if hasattr(route, "original_router")
        ]
        self.assertEqual(included_routers.count(auth.router), 1)
        self.assertEqual(included_routers.count(alerts.router), 1)
        for router in (auth.router, alerts.router):
            router_routes = [
                route for route in router.routes
                if getattr(route, "methods", None)
            ]
            route_counts = Counter(
                (method, route.path)
                for route in router_routes
                for method in route.methods
            )
            self.assertTrue(all(count == 1 for count in route_counts.values()), route_counts)

    def test_root_redirects_inactive_or_unauthenticated_users_to_login(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
        }
        request = Request(scope)
        with patch.object(
            main,
            "get_current_user",
            side_effect=HTTPException(status_code=401, detail="User no longer active"),
        ):
            response = main.home(request)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/login")

    def test_alerts_logout_link_targets_existing_route(self):
        html = Path(config.PROJECT_ROOT / "api" / "templates" / "alerts.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('href="/auth/logout"', html)
        self.assertNotIn('href="/logout"', html)
        self.assertIn("get", main.app.openapi()["paths"]["/auth/logout"])

    def test_auth_dependency_rejects_inactive_database_user(self):
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "headers": [(b"cookie", f"{COOKIE_NAME}=expired-user-session".encode())],
                "query_string": b"",
                "server": ("testserver", 80),
                "client": ("testclient", 50000),
                "scheme": "http",
            }
        )
        with (
            patch("api.security.decode_access_token", return_value={"sub": "inactive"}),
            patch("api.security.get_user_by_username", return_value={"id": 2, "is_active": 0}),
        ):
            with self.assertRaises(HTTPException) as error:
                get_current_user(request)
        self.assertEqual(error.exception.status_code, 401)

    def test_logout_clears_cookie_and_audits_identity_without_token_contents(self):
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/auth/logout",
                "headers": [(b"cookie", f"{COOKIE_NAME}=fake-jwt-value".encode())],
                "query_string": b"",
                "server": ("testserver", 80),
                "client": ("testclient", 50000),
                "scheme": "http",
            }
        )
        user = {"id": 17, "username": "reviewer", "is_active": 1}
        with (
            patch.object(auth, "decode_access_token", return_value={"sub": "reviewer"}),
            patch.object(auth, "get_user_by_username", return_value=user),
            patch.object(auth, "log_action") as audit,
        ):
            response = auth.logout(request)
        self.assertEqual(response.status_code, 303)
        self.assertIn("Max-Age=0", response.headers["set-cookie"])
        audit.assert_called_once_with(
            "reviewer",
            "LOGOUT",
            target="reviewer",
            details="actor_user_id=17",
        )
        self.assertNotIn("fake-jwt-value", repr(audit.call_args))

    def test_logout_clears_cookie_and_surfaces_audit_failure(self):
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/auth/logout",
                "headers": [(b"cookie", f"{COOKIE_NAME}=fake-jwt-value".encode())],
                "query_string": b"",
                "server": ("testserver", 80),
                "client": ("testclient", 50000),
                "scheme": "http",
            }
        )
        with (
            patch.object(auth, "decode_access_token", return_value={"sub": "reviewer"}),
            patch.object(
                auth,
                "get_user_by_username",
                return_value={"id": 17, "username": "reviewer"},
            ),
            patch.object(auth, "log_action", side_effect=RuntimeError("audit unavailable")),
        ):
            response = auth.logout(request)
        self.assertEqual(response.status_code, 503)
        self.assertIn("Max-Age=0", response.headers["set-cookie"])


class Phase5CaseAuditTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db_patch = patch.object(db, "DB_PATH", self.root / "phase5.db")
        self.db_patch.start()
        self.cases_patch = patch.object(config, "CASES_DIR", self.root / "cases")
        self.cases_patch.start()
        db.init_db()
        self.user_id = db.execute(
            """INSERT INTO users (username, password_hash, role)
               VALUES ('phase5-handler', 'not-a-real-password', 'Field Investigator')"""
        )

    def tearDown(self):
        self.cases_patch.stop()
        self.db_patch.stop()
        self.tempdir.cleanup()

    def test_case_entity_and_related_fir_changes_are_audited_and_hash_chained(self):
        create_case(
            "FIR-2026-P5A",
            {"district": "Test"},
            username="phase5-handler",
            handler_user_id=self.user_id,
        )
        create_case("FIR-2026-P5B", {"district": "Test"})
        entity_id = add_case_entity(
            "FIR-2026-P5A",
            "Synthetic account",
            "account",
            role="account",
            username="phase5-handler",
            actor_user_id=self.user_id,
        )
        self.assertTrue(
            record_related_fir_reference(
                "FIR-2026-P5A",
                "FIR-2026-P5B",
                username="phase5-handler",
                actor_user_id=self.user_id,
            )
        )
        events = get_audit_trail()
        actions = [event["action"] for event in events]
        self.assertIn("CASE_ENTITY_ADD", actions)
        self.assertIn("CASE_REFERENCE_CREATE", actions)
        self.assertTrue(
            any(
                event["target"] == f"FIR-2026-P5A:{entity_id}"
                and f"actor_user_id={self.user_id}" in event["details"]
                for event in events
            )
        )
        serialized_events = repr(events)
        self.assertNotIn("not-a-real-password", serialized_events)
        self.assertNotIn("jwt", serialized_events.lower())
        self.assertNotIn("token", serialized_events.lower())
        self.assertTrue(verify_chain()["valid"])

    def test_member_assignment_and_authorized_reference_read_are_audited(self):
        create_case("FIR-2026-P5A", {"district": "Test"})
        create_case("FIR-2026-P5B", {"district": "Test"})
        assign_case_member("FIR-2026-P5A", self.user_id, "handler", self.user_id)
        record_related_fir_reference(
            "FIR-2026-P5B",
            "FIR-2026-P5A",
            username="phase5-handler",
            actor_user_id=self.user_id,
        )
        from api.routers import case_vault

        case_vault.list_case_references(
            "FIR-2026-P5A",
            {"id": self.user_id, "username": "phase5-handler", "role": "Field Investigator"},
        )
        actions = [event["action"] for event in get_audit_trail()]
        self.assertIn("CASE_MEMBER_ASSIGNED", actions)
        self.assertIn("CASE_REFERENCE_DISCOVER", actions)
        self.assertTrue(verify_chain()["valid"])

    def test_case_creation_audit_failure_rolls_back_db_and_staged_files(self):
        with patch("core.case_manager.log_action", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                create_case("FIR-2026-P5FAIL", {"district": "Test"})
        self.assertIsNone(db.fetch_one("SELECT 1 FROM cases WHERE fir_id = ?", ("FIR-2026-P5FAIL",)))
        self.assertFalse(config.case_folder("FIR-2026-P5FAIL").exists())
        self.assertFalse(list(config.CASES_DIR.glob(".FIR-2026-P5FAIL.*.tmp")))

    def test_case_filesystem_failure_does_not_create_database_row(self):
        with patch("core.case_manager._create_case_folders_at", side_effect=OSError("disk unavailable")):
            with self.assertRaisesRegex(OSError, "disk unavailable"):
                create_case("FIR-2026-P5FAIL", {"district": "Test"})
        self.assertIsNone(db.fetch_one("SELECT 1 FROM cases WHERE fir_id = ?", ("FIR-2026-P5FAIL",)))
        self.assertFalse(config.case_folder("FIR-2026-P5FAIL").exists())

    def test_case_creation_never_removes_preexisting_orphaned_case_files(self):
        existing_folder = config.case_folder("FIR-2026-P5ORPHAN")
        existing_folder.mkdir(parents=True)
        sentinel = existing_folder / "protected-record.txt"
        sentinel.write_text("existing protected case data", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            create_case("FIR-2026-P5ORPHAN", {"district": "Test"})
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "existing protected case data")

    def test_case_database_failure_cleans_staging_files(self):
        with patch("core.case_manager.get_connection", side_effect=RuntimeError("database unavailable")):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                create_case("FIR-2026-P5FAIL", {"district": "Test"})
        self.assertFalse(config.case_folder("FIR-2026-P5FAIL").exists())
        self.assertFalse(list(config.CASES_DIR.glob(".FIR-2026-P5FAIL.*.tmp")))

    def test_status_update_audit_failure_rolls_back_database_and_restores_record(self):
        create_case("FIR-2026-P5A", {"district": "Test"})
        record_path = config.case_folder("FIR-2026-P5A") / "case_record.json"
        old_content = record_path.read_bytes()
        with patch("core.case_manager.log_action", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                update_case_status("FIR-2026-P5A", "Closed")
        self.assertEqual(db.fetch_one("SELECT status FROM cases WHERE fir_id = ?", ("FIR-2026-P5A",))["status"], "Open")
        self.assertEqual(record_path.read_bytes(), old_content)

    def test_status_update_database_and_filesystem_failures_preserve_both_records(self):
        create_case("FIR-2026-P5A", {"district": "Test"})
        record_path = config.case_folder("FIR-2026-P5A") / "case_record.json"
        original_content = record_path.read_bytes()
        with patch("core.case_manager.get_connection", side_effect=RuntimeError("database unavailable")):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                update_case_status("FIR-2026-P5A", "Closed")
        self.assertEqual(record_path.read_bytes(), original_content)
        self.assertEqual(db.fetch_one("SELECT status FROM cases WHERE fir_id = ?", ("FIR-2026-P5A",))["status"], "Open")

        with patch("pathlib.Path.replace", side_effect=OSError("filesystem unavailable")):
            with self.assertRaisesRegex(OSError, "filesystem unavailable"):
                update_case_status("FIR-2026-P5A", "Closed")
        self.assertEqual(record_path.read_bytes(), original_content)
        self.assertEqual(db.fetch_one("SELECT status FROM cases WHERE fir_id = ?", ("FIR-2026-P5A",))["status"], "Open")

    def test_logout_event_is_added_to_existing_hash_chain(self):
        from api.routers import auth

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/auth/logout",
                "headers": [(b"cookie", f"{COOKIE_NAME}=not-recorded".encode())],
                "query_string": b"",
                "server": ("testserver", 80),
                "client": ("testclient", 50000),
                "scheme": "http",
            }
        )
        with patch(
            "api.routers.auth.decode_access_token",
            return_value={"sub": "phase5-handler"},
        ):
            auth.logout(request)
        self.assertEqual(get_audit_trail(action="LOGOUT")[0]["username"], "phase5-handler")
        self.assertNotIn("not-recorded", repr(get_audit_trail(action="LOGOUT")))
        self.assertTrue(verify_chain()["valid"])


if __name__ == "__main__":
    unittest.main()
