import importlib
import os
import sqlite3
import unittest

import bcrypt

from backend.test_trust_features import TEST_DB, app_module

admin_routes_module = importlib.import_module("admin_routes")


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
                "admin_audit_log", "listing_reports", "listing_change_history",
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
            db.execute(
                """
                INSERT INTO listing_images (listing_id, image_url, "order")
                VALUES (?, ?, ?)
                """,
                (self.listing_id, "https://cdn.example.test/listing.jpg", 3),
            )
            db.commit()

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
            copied_image = db.execute(
                """
                SELECT image_url, "order"
                FROM listing_images
                WHERE listing_id = ?
                """,
                (duplicate_id,),
            ).fetchone()
        self.assertEqual(duplicate, ("Panel listing (Copy)", "draft"))
        self.assertEqual(
            copied_image,
            ("https://cdn.example.test/listing.jpg", 3),
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
        lead = self.client.get(
            f"/api/admin/leads/{lead_id}", headers=self._auth(self.admin_token)
        ).get_json()["lead"]
        self.assertEqual(lead["phone"], "+380501234567")
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
        verified = self.client.post(
            "/api/admin/agencies/panel-agency/verify",
            headers=self._auth(self.admin_token),
            json={"verified": True},
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


if __name__ == "__main__":
    unittest.main()
