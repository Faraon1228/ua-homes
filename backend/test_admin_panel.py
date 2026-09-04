import importlib
import os
import sqlite3
import unittest
from unittest import mock

import bcrypt

from backend.test_trust_features import TEST_DB, app_module

admin_routes_module = importlib.import_module("admin_routes")
system_status_module = importlib.import_module("system_status")


def setUpModule():
    if not os.path.exists(TEST_DB):
        os.makedirs(os.path.dirname(TEST_DB), exist_ok=True)
        app_module.init_db()


class AdminPanelTests(unittest.TestCase):
    def setUp(self):
        app_module.limiter.reset()
        self.client = app_module.app.test_client()
        with sqlite3.connect(TEST_DB) as db:
            db.execute("PRAGMA foreign_keys=ON")
            for table in (
                "admin_audit_log", "system_incidents", "system_status_snapshots",
                "listing_reports", "listing_change_history",
                "moderation_log", "lead_requests", "listing_images", "reviews",
                "listings", "agency_profiles", "users",
            ):
                db.execute(f"DELETE FROM {table}")
            self.admin_id = self._user(db, "Admin", "admin@staff.test", "admin")
            self.moderator_id = self._user(
                db, "Moderator", "moderator@staff.test", "moderator"
            )
            self.user_id = self._user(db, "User", "user@staff.test", "user")
            cursor = db.execute(
                """
                INSERT INTO listings (
                    user_id, title, city, district, price, rooms, area, status,
                    moderation_status, listing_verification_status
                ) VALUES (?, 'Panel listing', 'Київ', 'Центр', 100000, 2, 50,
                          'pending', 'pending_review', 'pending')
                """,
                (self.user_id,),
            )
            self.listing_id = cursor.lastrowid
            db.commit()
        self.admin_token = app_module.make_token(self.admin_id, "admin@staff.test")
        self.moderator_token = app_module.make_token(
            self.moderator_id, "moderator@staff.test"
        )
        self.user_token = app_module.make_token(self.user_id, "user@staff.test")

    @staticmethod
    def _user(db, name, email, role):
        password_hash = bcrypt.hashpw(b"staff-password", bcrypt.gensalt()).decode()
        cursor = db.execute(
            """
            INSERT INTO users (name, email, password, password_hash, role)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, email, password_hash, password_hash, role),
        )
        return cursor.lastrowid

    @staticmethod
    def _auth(token):
        return {"Authorization": f"Bearer {token}"}

    def _create_report(self, db, *, status="pending", key="admin-panel-report"):
        cursor = db.execute(
            """
            INSERT INTO listing_reports (
                listing_id, reporter_user_id, reporter_fingerprint,
                reason_code, details, status, idempotency_key
            ) VALUES (?, ?, 'secret-fingerprint', 'fraud', 'Review this', ?, ?)
            """,
            (self.listing_id, self.user_id, status, key),
        )
        return cursor.lastrowid

    def test_authorization_matrix_and_permission_boundaries(self):
        path = "/api/admin/listings"
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(
            self.client.get(path, headers=self._auth(self.user_token)).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(path, headers=self._auth(self.moderator_token)).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(path, headers=self._auth(self.admin_token)).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                path,
                headers=self._auth(self.moderator_token),
                json={"title": "Forbidden"},
            ).status_code,
            403,
        )
        for admin_only_path in (
            "/api/admin/users",
            "/api/admin/leads",
            "/api/admin/agencies",
            "/api/admin/developers",
            "/api/admin/system/health",
        ):
            self.assertEqual(
                self.client.get(
                    admin_only_path, headers=self._auth(self.moderator_token)
                ).status_code,
                403,
            )
        self.assertEqual(
            self.client.get(
                "/api/admin/audit", headers=self._auth(self.moderator_token)
            ).status_code,
            200,
        )

    def test_system_status_snapshot_refresh_is_admin_only_and_audited(self):
        health_path = "/api/admin/system/health"
        refresh_path = f"{health_path}/refresh"
        self.assertEqual(self.client.get(health_path).status_code, 401)
        self.assertEqual(
            self.client.post(refresh_path, headers=self._auth(self.moderator_token)).status_code,
            403,
        )
        refreshed = self.client.post(refresh_path, headers=self._auth(self.admin_token))
        self.assertEqual(refreshed.status_code, 200)
        payload = refreshed.get_json()
        self.assertEqual(payload["contract_version"], 1)
        self.assertIn(payload["overall_status"], {"ok", "degraded", "unknown", "down"})
        self.assertIn("database", payload["components"])
        self.assertNotIn("SENTRY_API_TOKEN", str(payload))
        self.assertEqual(
            self.client.get(health_path, headers=self._auth(self.admin_token)).status_code,
            200,
        )
        with sqlite3.connect(TEST_DB) as db:
            action = db.execute(
                "SELECT action FROM admin_audit_log ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
        self.assertIn("post:", action)

    def test_operations_status_refresh_requires_constant_time_shared_key(self):
        path = "/api/operations/system-status/refresh"
        self.assertEqual(self.client.post(path).status_code, 401)
        with mock.patch.dict(os.environ, {"UA_HOMES_STATUS_REFRESH_KEY": "shared-status-key"}):
            self.assertEqual(
                self.client.post(path, headers={"Authorization": "Bearer invalid"}).status_code,
                401,
            )
            response = self.client.post(
                path, headers={"Authorization": "Bearer shared-status-key"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("shared-status-key", response.get_data(as_text=True))

    def test_status_provider_payloads_are_scrubbed_and_allowlisted(self):
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        sentry_payload = [{
            "title": "Failure for person@example.test",
            "type": "RuntimeError",
            "firstSeen": now,
            "project": {"slug": "production"},
            "permalink": "https://evil.example/issue/1?token=leak",
        }]
        with mock.patch.dict(os.environ, {
            "SENTRY_API_TOKEN": "provider-token",
            "SENTRY_ORG": "ua-homes",
            "SENTRY_STATUS_PROJECTS": "production",
        }, clear=False), mock.patch.object(
            system_status_module, "_http_json", return_value=(200, sentry_payload, 1)
        ):
            component = system_status_module._sentry()
        self.assertEqual(component["critical_new_count"], 1)
        self.assertEqual(component["recent_issues"][0]["url"], None)
        self.assertNotIn("person@example.test", component["recent_issues"][0]["title"])
        self.assertNotIn("provider-token", str(component))

    def test_stale_status_snapshot_is_not_reported_as_fresh(self):
        system_status_module._CACHE.clear()
        stale = {
            "contract_version": 1, "overall_status": "ok", "generated_at": "2000-01-01T00:00:00+00:00",
            "stale": False, "components": {}, "production_version": {}, "notification_channels": {},
        }
        with sqlite3.connect(TEST_DB) as db:
            db.execute(
                "INSERT INTO system_status_snapshots (generated_at, overall_status, snapshot_json, refresh_duration_ms) VALUES (?, ?, ?, ?)",
                (stale["generated_at"], "ok", __import__("json").dumps(stale), 1),
            )
            db.commit()
        database = sqlite3.connect(TEST_DB)
        database.row_factory = sqlite3.Row
        snapshot = system_status_module.current_snapshot(database)
        database.close()
        self.assertTrue(snapshot["stale"])
        self.assertEqual(snapshot["overall_status"], "unknown")

    def test_push_status_accepts_legacy_naive_dispatch_timestamp(self):
        database = sqlite3.connect(TEST_DB)
        database.row_factory = sqlite3.Row
        database.execute(
            "INSERT INTO alert_dispatch_runs (trigger_type, success, started_at, finished_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("test", 1),
        )
        database.commit()
        with mock.patch.dict(os.environ, {"UA_HOMES_FIREBASE_SERVICE_ACCOUNT_BASE64": "configured"}, clear=False):
            component = system_status_module._push(database)
        database.close()
        self.assertEqual(component["status"], "ok")
        self.assertFalse(component["stale"])

    def test_staff_cookie_session_csrf_origin_logout_and_generic_login(self):
        for credentials in (
            {"email": "missing@staff.test", "password": "staff-password"},
            {"email": "user@staff.test", "password": "staff-password"},
            {"email": ["moderator@staff.test"], "password": "staff-password"},
            {"email": "moderator@staff.test", "password": 123},
        ):
            response = self.client.post("/api/admin/auth/login", json=credentials)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.get_json(), {"error": "Invalid credentials"})

        login = self.client.post(
            "/api/admin/auth/login",
            json={"email": "moderator@staff.test", "password": "staff-password"},
        )
        self.assertEqual(login.status_code, 200)
        payload = login.get_json()
        login_cookies = login.headers.getlist("Set-Cookie")
        session_cookie = next(
            value for value in login_cookies
            if value.startswith("ua_dim_staff_session=")
        )
        csrf_cookie = next(
            value for value in login_cookies
            if value.startswith("ua_dim_staff_csrf=")
        )
        self.assertIn("Path=/api/admin", session_cookie)
        self.assertIn("Path=/api/admin", csrf_cookie)
        self.assertIn("HttpOnly", session_cookie)
        self.assertIn("HttpOnly", csrf_cookie)
        self.assertNotIn("Secure", session_cookie)
        self.assertNotIn("Secure", csrf_cookie)
        self.assertEqual(payload["staff"]["role"], "moderator")
        self.assertIn("listings/moderate", payload["staff"]["permissions"])
        self.assertNotIn("users/manage", payload["staff"]["permissions"])

        reloaded = self.client.get("/api/admin/auth/session")
        self.assertEqual(reloaded.status_code, 200)
        reloaded_payload = reloaded.get_json()
        self.assertNotIn("token", reloaded_payload)
        self.assertEqual(reloaded_payload["csrf_token"], payload["csrf_token"])
        self.assertEqual(self.client.post("/api/admin/auth/logout").status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/admin/auth/logout",
                headers={
                    "X-CSRF-Token": reloaded_payload["csrf_token"],
                    "Origin": "https://evil.example",
                },
            ).status_code,
            403,
        )
        mutation = self.client.patch(
            f"/api/admin/verifications/{self.listing_id}",
            headers={"X-CSRF-Token": reloaded_payload["csrf_token"]},
            json={"listing_verification_status": "verified"},
        )
        self.assertEqual(mutation.status_code, 200)
        logout = self.client.post(
            "/api/admin/auth/logout",
            headers={"X-CSRF-Token": reloaded_payload["csrf_token"]},
        )
        self.assertEqual(logout.status_code, 200)
        deletion_cookies = logout.headers.getlist("Set-Cookie")
        for cookie_name in ("ua_dim_staff_session", "ua_dim_staff_csrf"):
            deleted = next(
                value for value in deletion_cookies
                if value.startswith(f"{cookie_name}=")
            )
            self.assertIn("Path=/api/admin", deleted)
            self.assertIn("Max-Age=0", deleted)
        self.assertEqual(
            self.client.get(
                "/api/admin/auth/session",
                headers=self._auth(payload["token"]),
            ).status_code,
            401,
        )

    def test_login_rate_limit(self):
        statuses = [
            self.client.post(
                "/api/admin/auth/login",
                json={"email": "missing@staff.test", "password": "wrong"},
            ).status_code
            for _ in range(11)
        ]
        self.assertEqual(statuses[:10], [401] * 10)
        self.assertEqual(statuses[10], 429)

    def test_suspended_and_revoked_staff_sessions(self):
        with sqlite3.connect(TEST_DB) as db:
            db.execute(
                "UPDATE users SET status = 'suspended' WHERE id = ?",
                (self.moderator_id,),
            )
            db.commit()
        self.assertEqual(
            self.client.get(
                "/api/admin/dashboard/stats",
                headers=self._auth(self.moderator_token),
            ).status_code,
            401,
        )
        with sqlite3.connect(TEST_DB) as db:
            db.execute(
                """
                UPDATE users SET status = 'active',
                    auth_token_version = auth_token_version + 1
                WHERE id = ?
                """,
                (self.moderator_id,),
            )
            db.commit()
        self.assertEqual(
            self.client.get(
                "/api/admin/dashboard/stats",
                headers=self._auth(self.moderator_token),
            ).status_code,
            401,
        )

    def test_last_admin_and_self_lockout_are_blocked(self):
        response = self.client.put(
            f"/api/admin/users/{self.admin_id}",
            headers=self._auth(self.admin_token),
            json={"role": "moderator", "status": "suspended"},
        )
        self.assertEqual(response.status_code, 409)
        with sqlite3.connect(TEST_DB) as db:
            row = db.execute(
                "SELECT role, status FROM users WHERE id = ?", (self.admin_id,)
            ).fetchone()
        self.assertEqual(row, ("admin", "active"))

    def test_duplicate_listing_copies_images_with_postgres_safe_order_identifier(self):
        insert_sql = admin_routes_module.LISTING_IMAGE_INSERT_SQL
        self.assertIn('"order"', insert_sql)
        self.assertNotIn("'order'", insert_sql)
        translated_sql = app_module._DbCursorProxy(
            None, None, is_postgres=True
        )._translate_query(insert_sql)
        self.assertEqual(translated_sql.count("%s"), 3)
        self.assertIn('"order"', translated_sql)

        with sqlite3.connect(TEST_DB) as db:
            db.executemany(
                """
                INSERT INTO listing_images (listing_id, image_url, "order")
                VALUES (?, ?, ?)
                """,
                (
                    (self.listing_id, "https://cdn.example.test/listing.jpg", 3),
                    (self.listing_id, "https://cdn.example.test/first.jpg", 1),
                ),
            )
            db.commit()

        detail = self.client.get(
            f"/api/admin/listings/{self.listing_id}",
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(
            [image["image_url"] for image in detail.get_json()["listing"]["images"]],
            [
                "https://cdn.example.test/first.jpg",
                "https://cdn.example.test/listing.jpg",
            ],
        )

        response = self.client.post(
            f"/api/admin/listings/{self.listing_id}/duplicate",
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, 201)
        duplicate_id = response.get_json()["id"]

        with sqlite3.connect(TEST_DB) as db:
            duplicate = db.execute(
                "SELECT title, status FROM listings WHERE id = ?",
                (duplicate_id,),
            ).fetchone()
            copied_images = db.execute(
                """
                SELECT image_url, "order"
                FROM listing_images
                WHERE listing_id = ?
                ORDER BY "order"
                """,
                (duplicate_id,),
            ).fetchall()
        self.assertEqual(duplicate, ("Panel listing (Copy)", "draft"))
        self.assertEqual(
            copied_images,
            [
                ("https://cdn.example.test/first.jpg", 1),
                ("https://cdn.example.test/listing.jpg", 3),
            ],
        )

    def test_report_contract_redaction_transition_and_transactional_audit(self):
        with sqlite3.connect(TEST_DB) as db:
            report_id = self._create_report(db)
            db.commit()
        queue = self.client.get(
            "/api/admin/listing-reports",
            headers=self._auth(self.moderator_token),
        )
        self.assertEqual(queue.status_code, 200)
        serialized = queue.get_json()["reports"][0]
        self.assertNotIn("reporter_fingerprint", serialized)
        self.assertNotIn("reporter_user_id", serialized)
        request_id = "admin-report-request-123"
        updated = self.client.patch(
            f"/api/admin/listing-reports/{report_id}",
            headers={
                **self._auth(self.moderator_token),
                "X-Request-ID": request_id,
            },
            json={"status": "resolved", "details": "must-not-enter-audit"},
        )
        self.assertEqual(updated.status_code, 200)
        with sqlite3.connect(TEST_DB) as db:
            report_status = db.execute(
                "SELECT status FROM listing_reports WHERE id = ?", (report_id,)
            ).fetchone()[0]
            audit = db.execute(
                """
                SELECT permission, metadata_json, request_id
                FROM admin_audit_log WHERE request_id = ?
                """,
                (request_id,),
            ).fetchone()
        self.assertEqual(report_status, "resolved")
        self.assertEqual(audit[0], "reports/manage")
        self.assertNotIn("must-not-enter-audit", audit[1])
        self.assertNotIn("details", audit[1])

    def test_rejected_mutation_does_not_persist_audit_entry(self):
        with sqlite3.connect(TEST_DB) as db:
            report_id = self._create_report(
                db, status="resolved", key="rejected-admin-panel-report"
            )
            db.commit()
        request_id = "rejected-admin-report-123"
        rejected = self.client.patch(
            f"/api/admin/listing-reports/{report_id}",
            headers={
                **self._auth(self.moderator_token),
                "X-Request-ID": request_id,
            },
            json={"status": "reviewing"},
        )
        self.assertEqual(rejected.status_code, 409)
        with sqlite3.connect(TEST_DB) as db:
            status = db.execute(
                "SELECT status FROM listing_reports WHERE id = ?", (report_id,)
            ).fetchone()[0]
            audit_count = db.execute(
                "SELECT COUNT(*) FROM admin_audit_log WHERE request_id = ?",
                (request_id,),
            ).fetchone()[0]
        self.assertEqual(status, "resolved")
        self.assertEqual(audit_count, 0)

    def test_verification_history_and_invalid_pagination(self):
        verified = self.client.patch(
            f"/api/admin/verifications/{self.listing_id}",
            headers=self._auth(self.moderator_token),
            json={"listing_verification_status": "verified"},
        )
        self.assertEqual(verified.status_code, 200)
        history = self.client.get(
            f"/api/admin/listings/{self.listing_id}/history",
            headers=self._auth(self.moderator_token),
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual(
            history.get_json()["history"][0]["field_name"],
            "listing_verification_status",
        )
        self.assertEqual(
            self.client.get(
                "/api/admin/listings?limit=0",
                headers=self._auth(self.moderator_token),
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                "/api/admin/dashboard/overview?period=forever",
                headers=self._auth(self.moderator_token),
            ).status_code,
            400,
        )

    def test_lead_pii_is_admin_only_and_agency_crud_is_audited(self):
        with sqlite3.connect(TEST_DB) as db:
            cursor = db.execute(
                """
                INSERT INTO lead_requests (
                    lead_type, source, name, phone, email, listing_id
                ) VALUES ('inquiry', 'listing_page', 'Buyer', '+380501234567',
                          'buyer@example.test', ?)
                """,
                (self.listing_id,),
            )
            lead_id = cursor.lastrowid
            db.commit()
        self.assertEqual(
            self.client.get(
                f"/api/admin/leads/{lead_id}",
                headers=self._auth(self.moderator_token),
            ).status_code,
            403,
        )
        forbidden_lead_update = self.client.patch(
            f"/api/admin/leads/{lead_id}",
            headers={
                **self._auth(self.moderator_token),
                "X-Request-ID": "moderator-lead-update",
            },
            json={"status": "closed"},
        )
        self.assertEqual(forbidden_lead_update.status_code, 403)
        lead = self.client.get(
            f"/api/admin/leads/{lead_id}", headers=self._auth(self.admin_token)
        ).get_json()["lead"]
        self.assertEqual(lead["phone"], "+380501234567")
        lead_updated = self.client.patch(
            f"/api/admin/leads/{lead_id}",
            headers={
                **self._auth(self.admin_token),
                "X-Request-ID": "admin-lead-update",
            },
            json={
                "status": "responded",
                "response_message": "Зателефонуємо сьогодні",
            },
        )
        self.assertEqual(lead_updated.status_code, 200)
        persisted_lead = self.client.get(
            f"/api/admin/leads/{lead_id}", headers=self._auth(self.admin_token)
        ).get_json()["lead"]
        self.assertEqual(persisted_lead["status"], "responded")
        self.assertEqual(
            persisted_lead["response_message"],
            "Зателефонуємо сьогодні",
        )
        created = self.client.post(
            "/api/admin/agencies",
            headers=self._auth(self.admin_token),
            json={
                "slug": "panel-agency",
                "name": "Panel Agency",
                "kind": "agency",
                "city": "Київ",
                "specialization": "",
                "avg_response_minutes": 18,
                "team_size": 7,
                "completed_deals": 43,
            },
        )
        self.assertEqual(created.status_code, 201)
        revision = created.get_json()["revision"]
        verified = self.client.post(
            "/api/admin/agencies/panel-agency/verify",
            headers=self._auth(self.admin_token),
            json={"verified": True, "revision": revision},
        )
        self.assertEqual(verified.status_code, 200)
        agency = self.client.get(
            "/api/admin/agencies/panel-agency",
            headers=self._auth(self.admin_token),
        ).get_json()["agency"]
        self.assertTrue(agency["is_verified"])
        self.assertEqual(agency["avg_response_minutes"], 18)
        self.assertEqual(agency["team_size"], 7)
        self.assertEqual(agency["completed_deals"], 43)
        self.assertEqual(agency["revision"], 2)
        with sqlite3.connect(TEST_DB) as db:
            self.assertEqual(
                db.execute(
                    "SELECT status, response_message FROM lead_requests WHERE id = ?",
                    (lead_id,),
                ).fetchone(),
                ("responded", "Зателефонуємо сьогодні"),
            )
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM admin_audit_log WHERE request_id = 'moderator-lead-update'"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                db.execute(
                    "SELECT permission FROM admin_audit_log WHERE request_id = 'admin-lead-update'"
                ).fetchone()[0],
                "leads/manage",
            )

    def test_existing_agency_schema_migration_restores_timestamp_contract(self):
        with sqlite3.connect(TEST_DB) as db:
            db.execute("DROP TABLE agency_profiles")
            db.execute(
                """
                CREATE TABLE agency_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'agency',
                    city TEXT NOT NULL,
                    specialization TEXT NOT NULL DEFAULT '',
                    is_verified INTEGER NOT NULL DEFAULT 0,
                    avg_response_minutes INTEGER,
                    team_size INTEGER,
                    completed_deals INTEGER NOT NULL DEFAULT 0,
                    last_verified_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            db.execute(
                """
                INSERT INTO agency_profiles (slug, name, city, created_at)
                VALUES ('legacy-agency', 'Legacy Agency', 'Київ', '2024-01-02 03:04:05')
                """
            )
            db.commit()

        app_module.init_db()

        with sqlite3.connect(TEST_DB) as db:
            updated_at = next(
                row
                for row in db.execute("PRAGMA table_info(agency_profiles)")
                if row[1] == "updated_at"
            )
            legacy_timestamps = db.execute(
                "SELECT created_at, updated_at FROM agency_profiles"
                " WHERE slug = 'legacy-agency'"
            ).fetchone()
        self.assertEqual(updated_at[3], 1)
        self.assertEqual(updated_at[4], "datetime('now')")
        self.assertEqual(
            legacy_timestamps,
            ("2024-01-02 03:04:05", "2024-01-02 03:04:05"),
        )

        for kind, path in (("agency", "agencies"), ("developer", "developers")):
            slug = f"migrated-{kind}"
            created = self.client.post(
                f"/api/admin/{path}",
                headers=self._auth(self.admin_token),
                json={"slug": slug, "name": f"Migrated {kind}", "city": "Львів"},
            )
            self.assertEqual(created.status_code, 201, created.get_json())
            detail = self.client.get(
                f"/api/admin/{path}/{slug}",
                headers=self._auth(self.admin_token),
            )
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.get_json()[kind]["slug"], slug)

        with sqlite3.connect(TEST_DB) as db:
            migrated_rows = db.execute(
                "SELECT kind, updated_at FROM agency_profiles"
                " WHERE slug IN ('migrated-agency', 'migrated-developer')"
                " ORDER BY kind"
            ).fetchall()
        self.assertEqual([row[0] for row in migrated_rows], ["agency", "developer"])
        self.assertTrue(all(row[1] for row in migrated_rows))

    def test_postgres_agency_migration_uses_text_timestamps_idempotently(self):
        class RecordingCursor:
            def __init__(self):
                self.statements = []

            def execute(self, statement):
                self.statements.append(" ".join(statement.split()))

        cursor = RecordingCursor()
        with mock.patch.object(app_module, "_is_postgres", return_value=True):
            app_module._migrate_postgres_agency_profiles(cursor)
            app_module._migrate_postgres_agency_profiles(cursor)

        expected_statements = [
            "ALTER TABLE agency_profiles ADD COLUMN IF NOT EXISTS status TEXT"
            " NOT NULL DEFAULT 'active'; ALTER TABLE agency_profiles ADD COLUMN"
            " IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 1; ALTER TABLE"
            " agency_profiles ADD COLUMN IF NOT EXISTS updated_at TEXT;",
            "UPDATE agency_profiles SET status = CASE WHEN status IN ('active',"
            " 'suspended') THEN status ELSE 'active' END, revision = CASE WHEN"
            " revision > 0 THEN revision ELSE 1 END, updated_at ="
            " COALESCE(updated_at, created_at, CAST(CURRENT_TIMESTAMP AS TEXT))",
            "ALTER TABLE agency_profiles ALTER COLUMN updated_at"
            " SET DEFAULT CAST(CURRENT_TIMESTAMP AS TEXT)",
            "ALTER TABLE agency_profiles ALTER COLUMN updated_at SET NOT NULL",
            "CREATE INDEX IF NOT EXISTS idx_agency_profiles_kind_status"
            " ON agency_profiles(kind, status)",
        ]
        self.assertEqual(cursor.statements[:5], expected_statements)
        self.assertEqual(cursor.statements[5:], expected_statements)

        class PostgresError(Exception):
            def __init__(self, sqlstate):
                self.sqlstate = sqlstate

        self.assertTrue(app_module._is_db_unique_error(PostgresError("23505")))
        self.assertFalse(app_module._is_db_unique_error(PostgresError("23502")))

        sqlite_db = sqlite3.connect(":memory:")
        sqlite_db.execute(
            "CREATE TABLE constraints (slug TEXT UNIQUE, required TEXT NOT NULL)"
        )
        sqlite_db.execute("INSERT INTO constraints VALUES ('existing', 'value')")
        with self.assertRaises(sqlite3.IntegrityError) as unique_error:
            sqlite_db.execute(
                "INSERT INTO constraints VALUES ('existing', 'other value')"
            )
        with self.assertRaises(sqlite3.IntegrityError) as not_null_error:
            sqlite_db.execute("INSERT INTO constraints VALUES ('new', NULL)")
        sqlite_db.close()
        self.assertTrue(app_module._is_db_unique_error(unique_error.exception))
        self.assertFalse(app_module._is_db_unique_error(not_null_error.exception))

    def test_developer_lifecycle_filters_concurrency_rbac_and_audit(self):
        forbidden_request_id = "moderator-developer-forbidden"
        forbidden = self.client.post(
            "/api/admin/developers",
            headers={
                **self._auth(self.moderator_token),
                "X-Request-ID": forbidden_request_id,
            },
            json={
                "slug": "forbidden-builder",
                "name": "Forbidden Builder",
                "city": "Київ",
            },
        )
        self.assertEqual(forbidden.status_code, 403)

        created = self.client.post(
            "/api/admin/developers",
            headers={
                **self._auth(self.admin_token),
                "X-Request-ID": "developer-create",
            },
            json={
                "slug": "north-star-build",
                "name": "North Star Build",
                "kind": "agency",
                "city": "Львів",
                "specialization": "Житлові комплекси",
                "avg_response_minutes": 25,
                "team_size": 12,
                "completed_deals": 90,
            },
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.get_json()["revision"], 1)

        listed = self.client.get(
            "/api/admin/developers?search=North&status=active&verified=false",
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(listed.status_code, 200)
        developers = listed.get_json()["developers"]
        self.assertEqual(len(developers), 1)
        self.assertEqual(developers[0]["kind"], "developer")
        self.assertEqual(developers[0]["revision"], 1)
        self.assertEqual(
            self.client.get(
                "/api/admin/agencies?search=North",
                headers=self._auth(self.admin_token),
            ).get_json()["total"],
            0,
        )

        updated = self.client.patch(
            "/api/admin/developers/north-star-build",
            headers={
                **self._auth(self.admin_token),
                "X-Request-ID": "developer-update",
            },
            json={"name": "North Star Development", "revision": 1},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["revision"], 2)

        stale = self.client.patch(
            "/api/admin/developers/north-star-build",
            headers={
                **self._auth(self.admin_token),
                "X-Request-ID": "developer-stale",
            },
            json={"city": "Одеса", "revision": 1},
        )
        self.assertEqual(stale.status_code, 409)

        verified = self.client.post(
            "/api/admin/developers/north-star-build/verify",
            headers=self._auth(self.admin_token),
            json={"verified": True, "revision": 2},
        )
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(verified.get_json()["revision"], 3)

        suspended = self.client.patch(
            "/api/admin/developers/north-star-build",
            headers=self._auth(self.admin_token),
            json={"status": "suspended", "revision": 3},
        )
        self.assertEqual(suspended.status_code, 200)
        self.assertEqual(suspended.get_json()["revision"], 4)
        detail = self.client.get(
            "/api/admin/developers/north-star-build",
            headers=self._auth(self.admin_token),
        ).get_json()["developer"]
        self.assertEqual(detail["name"], "North Star Development")
        self.assertEqual(detail["city"], "Львів")
        self.assertEqual(detail["status"], "suspended")
        self.assertFalse(detail["is_verified"])
        self.assertEqual(
            self.client.get("/api/agencies/north-star-build").status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                "/api/agencies?kind=developer&q=North"
            ).get_json()["agencies"],
            [],
        )

        rejected_verify = self.client.post(
            "/api/admin/developers/north-star-build/verify",
            headers={
                **self._auth(self.admin_token),
                "X-Request-ID": "developer-suspended-verify",
            },
            json={"verified": True, "revision": 4},
        )
        self.assertEqual(rejected_verify.status_code, 409)

        deleted = self.client.delete(
            "/api/admin/developers/north-star-build",
            headers=self._auth(self.admin_token),
            json={"revision": 4},
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(
            self.client.get(
                "/api/admin/developers/north-star-build",
                headers=self._auth(self.admin_token),
            ).status_code,
            404,
        )

        with sqlite3.connect(TEST_DB) as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM agency_profiles WHERE slug = 'north-star-build'"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM agency_profiles WHERE slug = 'forbidden-builder'"
                ).fetchone()[0],
                0,
            )
            for request_id in (
                forbidden_request_id,
                "developer-stale",
                "developer-suspended-verify",
            ):
                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM admin_audit_log WHERE request_id = ?",
                        (request_id,),
                    ).fetchone()[0],
                    0,
                )
            successful_audits = db.execute(
                """
                SELECT permission FROM admin_audit_log
                WHERE request_id IN ('developer-create', 'developer-update')
                ORDER BY request_id
                """
            ).fetchall()
        self.assertEqual(
            successful_audits,
            [("developers/manage",), ("developers/manage",)],
        )

    def test_developer_delete_rejects_linked_profiles_without_mutation_or_audit(self):
        created = self.client.post(
            "/api/admin/developers",
            headers=self._auth(self.admin_token),
            json={
                "slug": "linked-builder",
                "name": "Linked Builder",
                "city": "Київ",
            },
        )
        self.assertEqual(created.status_code, 201)
        suspended = self.client.patch(
            "/api/admin/developers/linked-builder",
            headers=self._auth(self.admin_token),
            json={"status": "suspended", "revision": 1},
        )
        self.assertEqual(suspended.status_code, 200)
        with sqlite3.connect(TEST_DB) as db:
            db.execute(
                "UPDATE users SET agency_slug = 'linked-builder' WHERE id = ?",
                (self.user_id,),
            )
            db.commit()
        rejected = self.client.delete(
            "/api/admin/developers/linked-builder",
            headers={
                **self._auth(self.admin_token),
                "X-Request-ID": "linked-developer-delete",
            },
            json={"revision": 2},
        )
        self.assertEqual(rejected.status_code, 409)
        with sqlite3.connect(TEST_DB) as db:
            profile = db.execute(
                "SELECT status, revision FROM agency_profiles WHERE slug = 'linked-builder'"
            ).fetchone()
            audit_count = db.execute(
                "SELECT COUNT(*) FROM admin_audit_log WHERE request_id = 'linked-developer-delete'"
            ).fetchone()[0]
        self.assertEqual(profile, ("suspended", 2))
        self.assertEqual(audit_count, 0)

    def test_listing_price_history_summary_and_audit_commit_atomically(self):
        created = self.client.post(
            "/api/admin/listings",
            headers={
                **self._auth(self.admin_token),
                "X-Request-ID": "listing-create-persist",
            },
            json={
                "title": "Persisted admin listing",
                "city": "Полтава",
                "district": "Центр",
                "price": 2_000_000,
                "rooms": 2,
                "area": 60,
                "status": "published",
            },
        )
        self.assertEqual(created.status_code, 201)
        listing_id = created.get_json()["id"]
        updated = self.client.put(
            f"/api/admin/listings/{listing_id}",
            headers={
                **self._auth(self.admin_token),
                "X-Request-ID": "listing-update-persist",
            },
            json={"price": 2_100_000, "status": "PUBLISHED"},
        )
        self.assertEqual(updated.status_code, 200)

        history = self.client.get(
            f"/api/admin/listings/{listing_id}/history",
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual(
            history.get_json()["price_history"][0],
            {
                "actor_type": "admin",
                "created_at": history.get_json()["price_history"][0]["created_at"],
                "field_name": "price",
                "new_value": "2100000",
                "old_value": "2000000",
            },
        )

        with sqlite3.connect(TEST_DB) as db:
            listing = db.execute(
                "SELECT price, status FROM listings WHERE id = ?", (listing_id,)
            ).fetchone()
            summary = db.execute(
                """
                SELECT published_count, price_sum
                FROM listing_city_summary WHERE city = 'Полтава'
                """
            ).fetchone()
            audits = db.execute(
                """
                SELECT request_id FROM admin_audit_log
                WHERE request_id IN ('listing-create-persist', 'listing-update-persist')
                ORDER BY request_id
                """
            ).fetchall()
        self.assertEqual(listing, (2_100_000, "published"))
        self.assertEqual(summary, (1, 2_100_000))
        self.assertEqual(
            audits,
            [("listing-create-persist",), ("listing-update-persist",)],
        )

    def test_observability_average_is_portable_to_postgres(self):
        class Result:
            @staticmethod
            def fetchall():
                return []

        class RecordingDatabase:
            def __init__(self):
                self.queries = []

            def execute(self, query, params=()):
                self.queries.append(query)
                return Result()

        database = RecordingDatabase()
        with (
            mock.patch.object(app_module, "cached_json_get", return_value=None),
            mock.patch.object(app_module, "cached_json_set"),
        ):
            report = admin_routes_module._build_observability_report(database, 24)

        self.assertEqual(report["vitals_by_metric"], [])
        self.assertTrue(
            any(
                "CAST(ROUND(CAST(AVG(metric_value) AS NUMERIC), 2) AS REAL)"
                in query
                for query in database.queries
            )
        )

    def test_lead_funnel_listing_query_is_portable_to_postgres(self):
        class Result:
            @staticmethod
            def fetchall():
                return []

            @staticmethod
            def fetchone():
                return {
                    "views": 0,
                    "intents": 0,
                    "submits": 0,
                    "redirects": 0,
                }

        class RecordingDatabase:
            def __init__(self):
                self.queries = []

            def execute(self, query, params=()):
                self.queries.append(query)
                return Result()

        database = RecordingDatabase()
        with (
            mock.patch.object(app_module, "cached_json_get", return_value=None),
            mock.patch.object(app_module, "cached_json_set"),
        ):
            report = admin_routes_module._build_lead_funnel_report(database, 30)

        self.assertEqual(report["top_listings"], [])
        listing_query = next(
            query
            for query in database.queries
            if "FROM lead_funnel_listing_metrics" in query
        )
        self.assertIn("GROUP BY lfm.listing_id, l.title", listing_query)
        self.assertNotIn("HAVING intents", listing_query)


if __name__ == "__main__":
    unittest.main()
