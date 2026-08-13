import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

import bcrypt


BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

TEST_DIR = tempfile.TemporaryDirectory()
TEST_DB = os.path.join(TEST_DIR.name, "trust-tests.db")
os.environ["UA_HOMES_DB_PATH"] = TEST_DB
os.environ["UA_HOMES_SECRET"] = "stage-five-test-secret-at-least-32-bytes"
os.environ.pop("DATABASE_URL", None)

app_module = importlib.import_module("app")


class TrustFeatureTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        TEST_DIR.cleanup()

    def setUp(self):
        self.client = app_module.app.test_client()
        app_module.limiter.reset()
        with sqlite3.connect(TEST_DB) as db:
            db.execute("PRAGMA foreign_keys=ON")
            for table in (
                "listing_reports",
                "listing_change_history",
                "moderation_log",
                "reviews",
                "listings",
                "users",
            ):
                db.execute(f"DELETE FROM {table}")
            self.owner_id = self._insert_user(db, "Owner", "owner@example.test", "owner")
            self.realtor_id = self._insert_user(db, "Realtor", "realtor@example.test", "realtor")
            self.admin_id = self._insert_user(db, "Admin", "admin@example.test", "owner", role="admin")
            self.target_id = self._insert_listing(
                db,
                self.owner_id,
                title="Target",
                price=100_000,
                area=50,
                status="published",
                listing_status="active",
                listing_verification_status="unverified",
            )
            self.realtor_listing_id = self._insert_listing(
                db,
                self.realtor_id,
                title="Realtor target",
                price=120_000,
                area=55,
                district="Шевченківський",
                status="published",
            )
            self.draft_id = self._insert_listing(
                db,
                self.owner_id,
                title="Draft",
                price=80_000,
                area=45,
                status="draft",
            )
            db.commit()

        self.owner_token = app_module.make_token(self.owner_id, "owner@example.test")
        self.realtor_token = app_module.make_token(self.realtor_id, "realtor@example.test")
        self.admin_token = app_module.make_token(self.admin_id, "admin@example.test")

    @staticmethod
    def _insert_user(db, name, email, account_type, role="user"):
        cursor = db.execute(
            "INSERT INTO users (name, email, password, role, account_type) VALUES (?, ?, ?, ?, ?)",
            (name, email, "hash", role, account_type),
        )
        return cursor.lastrowid

    @staticmethod
    def _insert_listing(
        db,
        user_id,
        *,
        title,
        price,
        area,
        city="Київ",
        district="Печерський",
        property_type="квартира",
        listing_type="sale",
        rooms=2,
        status="published",
        listing_status="active",
        listing_verification_status="unverified",
    ):
        cursor = db.execute(
            """
            INSERT INTO listings (
                user_id, title, city, district, property_type, condition_type,
                price, rooms, area, floor, total_floors, images, status,
                listing_type, listing_status, moderation_status,
                listing_verification_status, description
            ) VALUES (?, ?, ?, ?, ?, 'вторинка', ?, ?, ?, 1, 9, '[]', ?, ?, ?, 'approved', ?, '')
            """,
            (
                user_id,
                title,
                city,
                district,
                property_type,
                price,
                rooms,
                area,
                status,
                listing_type,
                listing_status,
                listing_verification_status,
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def _auth(token):
        return {"Authorization": f"Bearer {token}"}

    def test_schema_and_public_privacy_and_seller_type(self):
        with sqlite3.connect(TEST_DB) as db:
            listing_columns = {row[1] for row in db.execute("PRAGMA table_info(listings)")}
            report_columns = {row[1] for row in db.execute("PRAGMA table_info(listing_reports)")}
            history_columns = {row[1] for row in db.execute("PRAGMA table_info(listing_change_history)")}
        self.assertIn("listing_verification_status", listing_columns)
        self.assertIn("videos", listing_columns)
        self.assertIn("reporter_fingerprint", report_columns)
        self.assertIn("actor_type", history_columns)

        public = self.client.get(f"/api/listings/{self.target_id}")
        self.assertEqual(public.status_code, 200)
        listing = public.get_json()["listing"]
        self.assertNotIn("owner_email", listing)
        self.assertNotIn("moderation_reason", listing)
        self.assertEqual(listing["seller_type"], "owner")
        self.assertFalse(listing["verified_listing"])

        realtor = self.client.get(f"/api/listings/{self.realtor_listing_id}").get_json()["listing"]
        self.assertEqual(realtor["seller_type"], "intermediary")

    def test_admin_bootstrap_hashes_password_and_login_page_has_no_credentials(self):
        email = "secure-admin@example.test"
        password = "temporary-admin-password"
        with (
            mock.patch.object(app_module, "BOOTSTRAP_ADMIN_EMAIL", email),
            mock.patch.object(app_module, "BOOTSTRAP_ADMIN_PASSWORD", password),
            mock.patch.object(app_module, "BOOTSTRAP_ADMIN_NAME", "Secure Admin"),
            sqlite3.connect(TEST_DB) as db,
        ):
            app_module._bootstrap_admin_user(db)
            row = db.execute(
                "SELECT password, password_hash, role FROM users WHERE email = ?",
                (email,),
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertNotEqual(row[0], password)
        self.assertEqual(row[0], row[1])
        self.assertTrue(bcrypt.checkpw(password.encode(), row[1].encode()))
        self.assertEqual(row[2], "admin")

        login_page = os.path.join(
            os.path.dirname(BACKEND_DIR),
            "web",
            "admin",
            "login.html",
        )
        with open(login_page, encoding="utf-8") as stream:
            login_html = stream.read()
        self.assertNotIn("Demo Credentials:", login_html)
        self.assertNotIn("handleRegister", login_html)
        self.assertNotIn("/auth/register", login_html)

    def test_seller_create_publishes_media_and_delete_removes_listing(self):
        with sqlite3.connect(TEST_DB) as db:
            publisher_id = self._insert_user(db, "Publisher", "publisher@example.test", "owner")
            db.commit()
        publisher_token = app_module.make_token(publisher_id, "publisher@example.test")
        payload = {
            "title": "Media listing",
            "city": "Львів",
            "district": "Галицький",
            "propertyType": "квартира",
            "conditionType": "вторинка",
            "listingType": "sale",
            "price": 95_000,
            "rooms": 2,
            "area": 48,
            "floor": 3,
            "totalFloors": 7,
            "publishNow": True,
            "images": ["https://res.cloudinary.com/demo/image/upload/example.jpg"],
            "videos": [
                "https://res.cloudinary.com/demo/video/upload/example.mp4",
                "https://res.cloudinary.com/demo/video/upload/tour.mov",
            ],
        }
        created = self.client.post("/api/listings", json=payload, headers=self._auth(publisher_token))
        self.assertEqual(created.status_code, 201, created.get_json())
        listing = created.get_json()["listing"]
        self.assertEqual(listing["status"], "published")
        self.assertEqual(listing["videos"], payload["videos"])
        self.assertEqual(listing["image_count"], 1)
        self.assertEqual(listing["video_count"], 2)
        self.assertTrue(listing["has_video_tour"])

        catalog = self.client.get("/api/listings?status=published&limit=100").get_json()["listings"]
        self.assertIn(listing["id"], [item["id"] for item in catalog])
        detail_page = self.client.get(f"/listing/{listing['id']}")
        self.assertEqual(detail_page.status_code, 200)
        self.assertIn(b"<video controls playsinline", detail_page.data)
        self.assertIn(b"/video/upload/example.mp4", detail_page.data)

        forbidden = self.client.delete(
            f"/api/listings/{listing['id']}",
            headers=self._auth(self.realtor_token),
        )
        self.assertEqual(forbidden.status_code, 403)

        deleted = self.client.delete(
            f"/api/listings/{listing['id']}",
            headers=self._auth(publisher_token),
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get(f"/api/listings/{listing['id']}").status_code, 404)
        catalog_after_delete = self.client.get("/api/listings?status=published&limit=100").get_json()["listings"]
        self.assertNotIn(listing["id"], [item["id"] for item in catalog_after_delete])

    def test_media_upload_validation_rejects_unsafe_or_oversized_files(self):
        svg = self.client.post(
            "/api/media/presigned-url",
            json={"filename": "unsafe.svg", "contentType": "image/svg+xml", "size": 1024},
            headers=self._auth(self.owner_token),
        )
        self.assertEqual(svg.status_code, 400)

        oversized_video = self.client.post(
            "/api/media/presigned-url",
            json={
                "filename": "tour.mov",
                "contentType": "video/quicktime",
                "size": app_module.MAX_VIDEO_UPLOAD_SIZE + 1,
            },
            headers=self._auth(self.owner_token),
        )
        self.assertEqual(oversized_video.status_code, 413)

        arbitrary_url = self.client.post(
            "/api/media/confirm-upload",
            json={"url": "https://example.test/unsafe.mp4", "resourceType": "video"},
            headers=self._auth(self.owner_token),
        )
        self.assertEqual(arbitrary_url.status_code, 400)

    def test_upload_signing_uses_epoch_time_and_private_s3_requires_delivery_url(self):
        with app_module.app.test_request_context():
            app_module.g.user_id = self.owner_id
            with mock.patch.multiple(
                app_module,
                S3_ENABLED=True,
                S3_BUCKET=None,
                CLOUDINARY_URL="cloudinary://api-key:api-secret@test-cloud",
            ), mock.patch.object(app_module.time, "time", return_value=1_786_608_050):
                signed = app_module.generate_presigned_upload_url("photo.jpg", "image/jpeg")
            self.assertEqual(signed["timestamp"], 1_786_608_050)
            self.assertEqual(signed["authType"], "signed")

            with mock.patch.multiple(
                app_module,
                S3_ENABLED=True,
                S3_BUCKET="private-bucket",
                S3_ACCESS_KEY="access-key",
                S3_SECRET_KEY="secret-key",
                S3_PUBLIC_BASE_URL=None,
                CLOUDINARY_URL=None,
            ):
                self.assertIsNone(
                    app_module.generate_presigned_upload_url("photo.jpg", "image/jpeg")
                )

        with sqlite3.connect(TEST_DB) as db:
            db.execute(
                "UPDATE listings SET agency_slug = 'self-claimed-agency' WHERE id = ?",
                (self.realtor_listing_id,),
            )
            db.execute("UPDATE listings SET source = 'agency' WHERE id = ?", (self.target_id,))
            db.execute(
                "INSERT INTO users (name, email, password, account_type, plan_id)"
                " VALUES ('Developer', 'developer@example.test', 'hash', 'developer', '')"
            )
            developer_id = db.execute(
                "SELECT id FROM users WHERE email = 'developer@example.test'"
            ).fetchone()[0]
            db.commit()
        app_module.init_db()

        realtor = self.client.get(f"/api/listings/{self.realtor_listing_id}").get_json()["listing"]
        self.assertEqual(realtor["seller_type"], "intermediary")
        detail_html = self.client.get(f"/listing/{self.target_id}").get_data(as_text=True)
        self.assertIn("Тип продавця: <strong>Власник</strong>", detail_html)
        self.assertNotIn("Джерело: <strong>Агентство</strong>", detail_html)
        self.assertIn('"@type": "Person"', detail_html)
        with sqlite3.connect(TEST_DB) as db:
            developer = db.execute(
                "SELECT account_type, plan_id FROM users WHERE id = ?",
                (developer_id,),
            ).fetchone()
        self.assertEqual(developer, ("developer", "developer_free"))

    def test_s3_upload_confirmation_handles_client_and_missing_key_errors(self):
        owned_key = f"listings/{self.owner_id}/asset/photo.jpg"
        boto3_module = mock.Mock()
        boto3_module.client.side_effect = ValueError("invalid endpoint")
        with mock.patch.multiple(
            app_module,
            S3_BUCKET="private-bucket",
            S3_ACCESS_KEY="access-key",
            S3_SECRET_KEY="secret-key",
            S3_PUBLIC_BASE_URL="https://media.example.test",
        ), mock.patch.dict(sys.modules, {"boto3": boto3_module}):
            unavailable = self.client.post(
                "/api/media/confirm-upload",
                json={"key": owned_key},
                headers=self._auth(self.owner_token),
            )
        self.assertEqual(unavailable.status_code, 500)
        self.assertEqual(unavailable.get_json()["error"], "Failed to verify upload")

        missing_key_error = RuntimeError("missing")
        missing_key_error.response = {"Error": {"Code": "NoSuchKey"}}
        s3_client = mock.Mock()
        s3_client.head_object.side_effect = missing_key_error
        boto3_module = mock.Mock()
        boto3_module.client.return_value = s3_client
        with mock.patch.multiple(
            app_module,
            S3_BUCKET="private-bucket",
            S3_ACCESS_KEY="access-key",
            S3_SECRET_KEY="secret-key",
            S3_PUBLIC_BASE_URL="https://media.example.test",
        ), mock.patch.dict(sys.modules, {"boto3": boto3_module}):
            missing = self.client.post(
                "/api/media/confirm-upload",
                json={"key": owned_key},
                headers=self._auth(self.owner_token),
            )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.get_json()["error"], "File not found in S3")

    def test_distinct_listing_verification_permissions_and_history(self):
        owner_pending = self.client.patch(
            f"/api/listings/{self.target_id}/verification",
            headers=self._auth(self.owner_token),
            json={"listing_verification_status": "pending"},
        )
        self.assertEqual(owner_pending.status_code, 200)
        self.assertEqual(owner_pending.get_json()["listing"]["listing_verification_status"], "pending")

        owner_verified = self.client.patch(
            f"/api/listings/{self.target_id}/verification",
            headers=self._auth(self.owner_token),
            json={"listing_verification_status": "verified"},
        )
        self.assertEqual(owner_verified.status_code, 403)

        admin_verified = self.client.patch(
            f"/api/listings/{self.target_id}/verification",
            headers=self._auth(self.admin_token),
            json={"listing_verification_status": "verified"},
        )
        self.assertEqual(admin_verified.status_code, 200)
        verified = admin_verified.get_json()["listing"]
        self.assertTrue(verified["verified_listing"])
        self.assertEqual(verified["listing_verification_status"], "verified")

        trust = self.client.get(f"/api/listings/{self.target_id}/trust").get_json()
        self.assertTrue(trust["verified_listing"])
        transitions = [
            row for row in trust["history"] if row["field_name"] == "listing_verification_status"
        ]
        self.assertEqual([(row["old_value"], row["new_value"]) for row in transitions], [
            ("pending", "verified"),
            ("unverified", "pending"),
        ])
        self.assertNotIn("admin_id", trust["history"][0])

        owner_edit = self.client.patch(
            f"/api/listings/{self.target_id}",
            headers=self._auth(self.owner_token),
            json={
                "title": "Target with changed price",
                "city": "Київ",
                "district": "Печерський",
                "propertyType": "квартира",
                "conditionType": "вторинка",
                "price": 101_000,
                "rooms": 2,
                "area": 50,
                "floor": 1,
                "totalFloors": 9,
                "listingType": "sale",
                "listingStatus": "active",
                "images": [],
                "description": "",
            },
        )
        self.assertEqual(owner_edit.status_code, 200)
        edited = owner_edit.get_json()["listing"]
        self.assertEqual(edited["listing_verification_status"], "pending")
        self.assertFalse(edited["verified_listing"])
        updated_trust = self.client.get(f"/api/listings/{self.target_id}/trust").get_json()
        self.assertEqual(updated_trust["history"][0]["old_value"], "verified")
        self.assertEqual(updated_trust["history"][0]["new_value"], "pending")

    def test_anonymous_report_validation_idempotency_and_duplicate_block(self):
        invalid = self.client.post(
            f"/api/listings/{self.target_id}/reports",
            json={
                "reason_code": "fraud_scam",
                "details": "short",
                "reporter_session_id": "reporter-session-01",
                "idempotency_key": "report-idem-01",
            },
        )
        self.assertEqual(invalid.status_code, 422)

        payload = {
            "reason_code": "fraud_scam",
            "details": "Контакт просить передоплату до перегляду квартири.",
            "reporter_session_id": "reporter-session-01",
            "idempotency_key": "report-idem-01",
        }
        created = self.client.post(f"/api/listings/{self.target_id}/reports", json=payload)
        self.assertEqual(created.status_code, 201)
        result = created.get_json()
        self.assertFalse(result["duplicate"])
        self.assertNotIn("reporter_fingerprint", result["report"])
        self.assertNotIn("reporter_user_id", result["report"])

        retry = self.client.post(
            f"/api/listings/{self.target_id}/reports",
            json=payload,
            headers={"User-Agent": "Changed browser"},
            environ_base={"REMOTE_ADDR": "203.0.113.25"},
        )
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.get_json()["duplicate"])

        key_conflict = self.client.post(
            f"/api/listings/{self.target_id}/reports",
            json={**payload, "reason_code": "spam"},
        )
        self.assertEqual(key_conflict.status_code, 409)
        self.assertEqual(key_conflict.get_json()["code"], "idempotency_conflict")

        duplicate = self.client.post(
            f"/api/listings/{self.target_id}/reports",
            json={**payload, "idempotency_key": "report-idem-02"},
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.get_json()["code"], "duplicate_report")

        with sqlite3.connect(TEST_DB) as db:
            row = db.execute(
                "SELECT reporter_fingerprint, details FROM listing_reports WHERE listing_id = ?",
                (self.target_id,),
            ).fetchone()
        self.assertEqual(len(row[0]), 64)
        self.assertNotIn("reporter-session-01", row[0])
        self.assertEqual(row[1], payload["details"])

    def test_authenticated_report_and_private_listing_policy(self):
        report = self.client.post(
            f"/api/listings/{self.target_id}/reports",
            headers=self._auth(self.owner_token),
            json={
                "reason_code": "other",
                "details": "Власник тестує авторизований канал скарг.",
                "idempotency_key": "auth-report-01",
            },
        )
        self.assertEqual(report.status_code, 201)
        with sqlite3.connect(TEST_DB) as db:
            reporter_user_id = db.execute(
                "SELECT reporter_user_id FROM listing_reports WHERE id = ?",
                (report.get_json()["report"]["id"],),
            ).fetchone()[0]
        self.assertEqual(reporter_user_id, self.owner_id)

        self.assertEqual(self.client.get(f"/api/listings/{self.draft_id}/trust").status_code, 404)
        owner_view = self.client.get(
            f"/api/listings/{self.draft_id}/trust",
            headers=self._auth(self.owner_token),
        )
        self.assertEqual(owner_view.status_code, 200)

    def test_comparable_medians_and_insufficient_data(self):
        with sqlite3.connect(TEST_DB) as db:
            for index, (price, area) in enumerate(((90_000, 45), (110_000, 50), (130_000, 55)), 1):
                self._insert_listing(
                    db,
                    self.owner_id,
                    title=f"Comparable {index}",
                    price=price,
                    area=area,
                )
            self._insert_listing(
                db,
                self.owner_id,
                title="Wrong district outlier",
                price=999_000,
                area=50,
                district="Оболонський",
            )
            self._insert_listing(
                db,
                self.owner_id,
                title="Sold outlier",
                price=999_000,
                area=50,
                listing_status="sold",
            )
            db.commit()

        stats = self.client.get(f"/api/listings/{self.target_id}/trust").get_json()["price_statistics"]
        self.assertEqual(stats["status"], "ok")
        self.assertEqual(stats["sample_size"], 3)
        self.assertEqual(stats["median_price"], 110_000)
        self.assertAlmostEqual(stats["median_price_per_sqm"], 2_200)

        insufficient = self.client.get(
            f"/api/listings/{self.realtor_listing_id}/trust"
        ).get_json()["price_statistics"]
        self.assertEqual(insufficient["status"], "insufficient_data")
        self.assertEqual(insufficient["sample_size"], 0)
        self.assertIsNone(insufficient["median_price"])

    def test_comparable_statistics_are_not_truncated_to_200_rows(self):
        with sqlite3.connect(TEST_DB) as db:
            for index in range(201):
                self._insert_listing(
                    db,
                    self.owner_id,
                    title=f"Full sample {index}",
                    price=90_000 + index,
                    area=50,
                )
            db.commit()

        stats = self.client.get(f"/api/listings/{self.target_id}/trust").get_json()["price_statistics"]
        self.assertEqual(stats["status"], "ok")
        self.assertEqual(stats["sample_size"], 201)

    def test_price_update_creates_real_sanitized_history(self):
        response = self.client.patch(
            f"/api/listings/{self.target_id}",
            headers=self._auth(self.owner_token),
            json={
                "title": "Target updated",
                "city": "Київ",
                "district": "Печерський",
                "propertyType": "квартира",
                "conditionType": "вторинка",
                "price": 105_000,
                "rooms": 2,
                "area": 50,
                "floor": 1,
                "totalFloors": 9,
                "listingType": "sale",
                "listingStatus": "active",
                "images": [],
                "description": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        trust = self.client.get(f"/api/listings/{self.target_id}/trust").get_json()
        price_rows = [row for row in trust["history"] if row["field_name"] == "price"]
        self.assertEqual(len(price_rows), 1)
        self.assertEqual(price_rows[0]["old_value"], "100000")
        self.assertEqual(price_rows[0]["new_value"], "105000")
        self.assertEqual(price_rows[0]["actor_type"], "owner")

    def test_postgres_cursor_exposes_captured_lastval(self):
        class FakeCursor:
            lastrowid = None

            def __init__(self):
                self.query = ""

            def execute(self, query, params=None):
                self.query = query

            def fetchone(self):
                return {"lastrowid": 42} if self.query.startswith("SELECT LASTVAL()") else None

        proxy = app_module._DbCursorProxy(None, FakeCursor(), is_postgres=True)
        proxy.execute("INSERT INTO listing_reports (listing_id) VALUES (?)", (1,))
        self.assertEqual(proxy.lastrowid, 42)


if __name__ == "__main__":
    unittest.main()
