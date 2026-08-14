import base64
import importlib
import io
import json
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
media_migration = importlib.import_module("migrate_legacy_listing_media")
operations_backup = importlib.import_module("operations_backup")


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
                "client_observability_events",
                "premium_orders",
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

    def test_health_checks_database_and_correlates_requests(self):
        request_id = "operations-test-request-123"
        response = self.client.get("/api/health", headers={"X-Request-ID": request_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["database"], "ok")
        self.assertEqual(response.headers["X-Request-ID"], request_id)

        with mock.patch.object(app_module, "get_db", side_effect=sqlite3.OperationalError("offline")):
            unavailable = self.client.get("/api/health")
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable.get_json()["database"], "unavailable")
        self.assertRegex(unavailable.headers["X-Request-ID"], r"^[a-f0-9]{24}$")

    def test_authenticated_backup_export_and_restore_drill(self):
        with mock.patch.dict(os.environ, {"UA_HOMES_BACKUP_TOKEN": ""}):
            not_configured = self.client.post("/api/operations/backup")
        self.assertEqual(not_configured.status_code, 503)

        with tempfile.TemporaryDirectory() as temporary_directory:
            export_directory = os.path.join(temporary_directory, "export")
            os.mkdir(export_directory)
            with mock.patch.dict(os.environ, {"UA_HOMES_BACKUP_TOKEN": "backup-test-token"}):
                unauthorized = self.client.post(
                    "/api/operations/backup",
                    headers={"Authorization": "Bearer wrong-token"},
                )
                self.assertEqual(unauthorized.status_code, 401)

                app_module.limiter.reset()
                with mock.patch.object(
                    app_module.tempfile,
                    "mkdtemp",
                    return_value=export_directory,
                ):
                    response = self.client.post(
                        "/api/operations/backup",
                        headers={"Authorization": "Bearer backup-test-token"},
                        buffered=True,
                    )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "private, no-store")
            self.assertRegex(response.headers["X-Backup-SHA256"], r"^[a-f0-9]{64}$")
            backup_sha256 = response.headers["X-Backup-SHA256"]
            backup_bytes = response.data
            response.close()
            self.assertFalse(os.path.exists(export_directory))

            backup_path = os.path.join(temporary_directory, "backup.sqlite3")
            with open(backup_path, "wb") as backup_file:
                backup_file.write(backup_bytes)
            summary = operations_backup.verify_database(backup_path)
            drill = operations_backup.restore_drill(backup_path)

        self.assertEqual(summary["sha256"], backup_sha256)
        self.assertEqual(summary["row_counts"], {"users": 3, "listings": 3})
        self.assertEqual(drill["restore_drill"], "ok")

    def test_client_observability_strips_query_and_fragment(self):
        response = self.client.post(
            "/api/analytics/client-telemetry",
            json={
                "event_type": "runtime_error",
                "message": "Test failure",
                "page_url": "https://test-user:test-password@ua-dim.com/seller?reset_token=secret#private",
            },
        )
        self.assertEqual(response.status_code, 201)
        with sqlite3.connect(TEST_DB) as database:
            stored_url = database.execute(
                "SELECT page_url FROM client_observability_events ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
        self.assertEqual(stored_url, "https://ua-dim.com/seller")

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
        detail_html = detail_page.get_data(as_text=True)
        self.assertLess(detail_html.index('id="listing-price"'), detail_html.index('id="gallery"'))

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

    def test_legacy_base64_listing_photos_are_rejected_and_not_serialized(self):
        data_uri = "data:image/jpeg;base64," + base64.b64encode(b"legacy-photo").decode("ascii")
        payload = {
            "title": "Legacy image",
            "city": "Київ",
            "district": "Печерський",
            "propertyType": "квартира",
            "conditionType": "вторинка",
            "listingType": "sale",
            "price": 100_000,
            "rooms": 2,
            "area": 50,
            "images": [data_uri],
        }
        rejected = self.client.post(
            "/api/listings",
            json=payload,
            headers=self._auth(self.owner_token),
        )
        self.assertEqual(rejected.status_code, 422)
        self.assertIn("images", rejected.get_json()["fields"])

        multipart = self.client.post(
            "/api/listings",
            data={
                "payload": json.dumps({**payload, "images": []}),
                "images": (io.BytesIO(b"legacy-photo"), "photo.jpg"),
            },
            content_type="multipart/form-data",
            headers=self._auth(self.owner_token),
        )
        self.assertEqual(multipart.status_code, 422)
        self.assertIn("images", multipart.get_json()["fields"])

        with sqlite3.connect(TEST_DB) as db:
            db.execute(
                "UPDATE listings SET images = ? WHERE id = ?",
                (json.dumps([data_uri]), self.target_id),
            )
            db.commit()
        public_listing = self.client.get(f"/api/listings/{self.target_id}").get_json()["listing"]
        self.assertEqual(public_listing["images"], [app_module.PLACEHOLDER_LISTING_IMAGE])

        blocked_edit = self.client.patch(
            f"/api/listings/{self.target_id}",
            json={**payload, "images": []},
            headers=self._auth(self.owner_token),
        )
        self.assertEqual(blocked_edit.status_code, 409)
        self.assertEqual(blocked_edit.get_json()["code"], "legacy_media_pending")

    def test_legacy_media_migration_preserves_schema_and_concurrent_edits(self):
        data_uri = "data:image/jpeg;base64," + base64.b64encode(b"legacy-photo").decode("ascii")
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE listings (id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT, images TEXT)")
        db.execute(
            "INSERT INTO listings (id, user_id, title, images) VALUES (1, 7, 'Legacy', ?)",
            (json.dumps([data_uri]),),
        )
        db.commit()

        rows = media_migration.load_candidates(db, [])
        with mock.patch.object(
            media_migration.cloudinary.uploader,
            "upload",
            return_value={"secure_url": "https://res.cloudinary.com/demo/image/upload/recovered.jpg"},
        ):
            stats = media_migration.migrate(db, rows, apply=True)
        self.assertEqual(stats["migrated"], 1)
        self.assertEqual(stats["failed"], 0)
        stored = json.loads(db.execute("SELECT images FROM listings WHERE id = 1").fetchone()[0])
        self.assertEqual(
            stored,
            ["https://res.cloudinary.com/demo/image/upload/recovered.jpg"],
        )

        db.execute("UPDATE listings SET images = ? WHERE id = 1", (json.dumps([data_uri]),))
        db.commit()
        stale_rows = media_migration.load_candidates(db, [])
        concurrent_value = json.dumps(["https://example.test/concurrent.jpg"])
        db.execute("UPDATE listings SET images = ? WHERE id = 1", (concurrent_value,))
        db.commit()
        with mock.patch.object(
            media_migration.cloudinary.uploader,
            "upload",
            return_value={"secure_url": "https://res.cloudinary.com/demo/image/upload/stale.jpg"},
        ):
            conflict_stats = media_migration.migrate(db, stale_rows, apply=True)
        self.assertEqual(conflict_stats["conflicts"], 1)
        self.assertEqual(db.execute("SELECT images FROM listings WHERE id = 1").fetchone()[0], concurrent_value)
        db.close()

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
        self.assertIn("<strong>Продавець:</strong> Власник", detail_html)
        self.assertNotIn("Джерело: <strong>Агентство</strong>", detail_html)
        self.assertIn('"@type": "Person"', detail_html)
        self.assertIn("UA-Dim", detail_html)
        self.assertNotIn("UA Homes", detail_html)
        self.assertIn("mailto:feedback@ua-dim.com", detail_html)
        self.assertIn("Запитати про об’єкт", detail_html)
        self.assertIn("До каталогу UA-Dim", detail_html)
        self.assertNotIn("Trust-flow", detail_html)
        self.assertIn('<details class="disclosure" id="verification-details">', detail_html)
        self.assertIn("Ціна та відповіді на запитання", detail_html)
        self.assertNotIn("Що відомо про оголошення", detail_html)
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

    # ─── Stage-2 auth hardening tests ─────────────────────────────────────────

    def test_forgot_password_schema_migrations_present(self):
        """password_reset_token_hash / password_reset_expires columns must exist."""
        with sqlite3.connect(TEST_DB) as db:
            cols = {row[1] for row in db.execute("PRAGMA table_info(users)")}
        self.assertIn("password_reset_token_hash", cols)
        self.assertIn("password_reset_expires", cols)
        self.assertIn("auth_token_version", cols)

    def test_forgot_password_unknown_email_is_non_enumerating(self):
        """POST /api/auth/forgot-password returns 200 even for unknown email."""
        resp = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "nobody@example.test"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("ok"))

    def test_forgot_password_missing_provider_in_production_returns_503(self):
        """In production with no email provider configured, return 503 before claiming delivery."""
        with (
            mock.patch.object(app_module, "_production_secret_required", return_value=True),
            mock.patch.object(app_module, "_email_provider_configured", return_value=False),
        ):
            resp = self.client.post(
                "/api/auth/forgot-password",
                json={"email": "owner@example.test"},
            )
        self.assertEqual(resp.status_code, 503)

    def test_forgot_password_delivery_failure_stays_non_enumerating_and_clears_token(self):
        """A provider failure must not reveal account existence or leave a usable token."""
        with (
            mock.patch.object(app_module, "_production_secret_required", return_value=True),
            mock.patch.object(app_module, "_email_provider_configured", return_value=True),
            mock.patch.object(app_module, "_send_email", return_value=False),
        ):
            known = self.client.post(
                "/api/auth/forgot-password",
                json={"email": "owner@example.test"},
            )
            unknown = self.client.post(
                "/api/auth/forgot-password",
                json={"email": "nobody@example.test"},
            )

        self.assertEqual(known.status_code, 200)
        self.assertEqual(known.get_json(), unknown.get_json())
        with sqlite3.connect(TEST_DB) as db:
            row = db.execute(
                "SELECT password_reset_token_hash, password_reset_expires FROM users WHERE id=?",
                (self.owner_id,),
            ).fetchone()
        self.assertEqual(row, (None, None))

    def test_forgot_password_keeps_reset_token_out_of_request_url(self):
        """Reset links use a fragment so proxies and access logs do not receive the token."""
        with (
            mock.patch.object(app_module, "_production_secret_required", return_value=True),
            mock.patch.object(app_module, "_email_provider_configured", return_value=True),
            mock.patch.object(app_module, "public_seller_url", return_value="https://ua-dim.com/seller"),
            mock.patch.object(app_module, "_send_email", return_value=True) as send_email,
        ):
            response = self.client.post(
                "/api/auth/forgot-password",
                json={"email": "owner@example.test"},
            )

        self.assertEqual(response.status_code, 200)
        text_body = send_email.call_args.args[2]
        html_body = send_email.call_args.args[3]
        self.assertIn("#reset_token=", text_body)
        self.assertIn("#reset_token=", html_body)
        self.assertIn("/seller#reset_token=", text_body)
        self.assertIn("/seller#reset_token=", html_body)
        self.assertNotIn("?reset_token=", text_body)
        self.assertNotIn("?reset_token=", html_body)

    def test_sendgrid_uses_bearer_authorization(self):
        response = mock.MagicMock()
        response.status = 202
        response.__enter__.return_value = response
        with (
            mock.patch.dict(os.environ, {"SENDGRID_API_KEY": "test-sendgrid-key"}),
            mock.patch("urllib.request.urlopen", return_value=response) as urlopen,
        ):
            sent = app_module._send_email(
                "recipient@example.test",
                "Subject",
                "Text",
                "<p>Text</p>",
            )

        self.assertTrue(sent)
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.get_header("Authorization"),
            "Bearer " + "test-sendgrid-key",
        )

    def test_reset_password_token_hash_expiry_single_use_and_login(self):
        """Full reset flow: token stored as hash, bcrypt password set, replay rejected, login works."""
        import hashlib, datetime as dt

        # ── Issue a reset token ──────────────────────────────────────────────
        raw_token = "test-raw-token-for-reset-flow-abc123"
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires = (dt.datetime.utcnow() + dt.timedelta(minutes=30)).isoformat()
        with sqlite3.connect(TEST_DB) as db:
            db.execute(
                "UPDATE users SET password_reset_token_hash=?, password_reset_expires=? WHERE id=?",
                (token_hash, expires, self.owner_id),
            )
            db.commit()

        # ── Verify raw token is NOT stored in the DB ─────────────────────────
        with sqlite3.connect(TEST_DB) as db:
            row = db.execute(
                "SELECT password_reset_token_hash FROM users WHERE id=?", (self.owner_id,)
            ).fetchone()
        self.assertNotEqual(row[0], raw_token, "Raw token must not be stored")
        self.assertEqual(row[0], token_hash)

        # ── Reset with valid token ────────────────────────────────────────────
        resp = self.client.post(
            "/api/auth/reset-password",
            json={"token": raw_token, "password": "newpassword123"},
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())

        # ── Token fields must be cleared (no replay) ─────────────────────────
        with sqlite3.connect(TEST_DB) as db:
            row = db.execute(
                "SELECT password_reset_token_hash, password_reset_expires, password_hash"
                " FROM users WHERE id=?",
                (self.owner_id,),
            ).fetchone()
        self.assertIsNone(row[0])
        self.assertIsNone(row[1])
        self.assertTrue(bcrypt.checkpw(b"newpassword123", row[2].encode()))

        # ── Login with new password succeeds ─────────────────────────────────
        login_resp = self.client.post(
            "/api/auth/login",
            json={"email": "owner@example.test", "password": "newpassword123"},
        )
        self.assertEqual(login_resp.status_code, 200)
        new_token = login_resp.get_json()["token"]
        self.assertEqual(
            self.client.get("/api/auth/me", headers=self._auth(self.owner_token)).status_code,
            401,
        )
        self.assertEqual(
            self.client.get("/api/auth/me", headers=self._auth(new_token)).status_code,
            200,
        )

        # ── Replay of same token is rejected ─────────────────────────────────
        replay = self.client.post(
            "/api/auth/reset-password",
            json={"token": raw_token, "password": "anotherpassword"},
        )
        self.assertEqual(replay.status_code, 400)

    def test_reset_password_rejects_expired_token(self):
        """An expired reset token returns 400 without leaking details."""
        import hashlib, datetime as dt

        raw_token = "expired-token-xyz"
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires = (dt.datetime.utcnow() - dt.timedelta(minutes=1)).isoformat()
        with sqlite3.connect(TEST_DB) as db:
            db.execute(
                "UPDATE users SET password_reset_token_hash=?, password_reset_expires=? WHERE id=?",
                (token_hash, expires, self.owner_id),
            )
            db.commit()

        resp = self.client.post(
            "/api/auth/reset-password",
            json={"token": raw_token, "password": "validpassword"},
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertNotIn("email", str(body))
        self.assertNotIn(raw_token, str(body))

    def test_reset_password_rejects_short_password(self):
        resp = self.client.post(
            "/api/auth/reset-password",
            json={"token": "any-token", "password": "short"},
        )
        self.assertEqual(resp.status_code, 422)

    def test_send_phone_code_no_twilio_dev_returns_dev_code(self):
        """Without Twilio and not in production, dev_code is returned and code is persisted."""
        with mock.patch.object(app_module, "_production_secret_required", return_value=False):
            resp = self.client.post(
                "/api/auth/send-phone-code",
                json={"phone": "+380501234567"},
                headers=self._auth(self.owner_token),
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsNotNone(data.get("dev_code"), "dev_code must be present in dev mode")
        with sqlite3.connect(TEST_DB) as db:
            row = db.execute(
                "SELECT phone_verify_code FROM users WHERE id=?", (self.owner_id,)
            ).fetchone()
        self.assertIsNotNone(row[0], "code must be persisted in dev mode")

    def test_send_phone_code_no_twilio_production_returns_503_no_storage(self):
        """In production without Twilio, 503 is returned and no code is stored."""
        with sqlite3.connect(TEST_DB) as db:
            db.execute(
                "UPDATE users SET phone_verify_code=NULL, phone_verify_expires=NULL WHERE id=?",
                (self.owner_id,),
            )
            db.commit()

        with mock.patch.object(app_module, "_production_secret_required", return_value=True):
            resp = self.client.post(
                "/api/auth/send-phone-code",
                json={"phone": "+380501234567"},
                headers=self._auth(self.owner_token),
            )
        self.assertEqual(resp.status_code, 503)

        with sqlite3.connect(TEST_DB) as db:
            row = db.execute(
                "SELECT phone_verify_code FROM users WHERE id=?", (self.owner_id,)
            ).fetchone()
        self.assertIsNone(row[0], "no code must be stored when 503 is returned")

    def test_send_phone_code_twilio_send_failure_returns_502_no_storage(self):
        """If Twilio is configured but send fails, return 502 and do not store code."""
        with sqlite3.connect(TEST_DB) as db:
            db.execute(
                "UPDATE users SET phone_verify_code=NULL WHERE id=?", (self.owner_id,)
            )
            db.commit()

        with (
            mock.patch.dict(os.environ, {
                "TWILIO_ACCOUNT_SID": "ACtest",
                "TWILIO_AUTH_TOKEN": "authtoken",
                "TWILIO_FROM_PHONE": "+15550000000",
            }),
            mock.patch.object(app_module, "send_sms_verify", return_value=False),
        ):
            resp = self.client.post(
                "/api/auth/send-phone-code",
                json={"phone": "+380501234567"},
                headers=self._auth(self.owner_token),
            )
        self.assertEqual(resp.status_code, 502)

        with sqlite3.connect(TEST_DB) as db:
            row = db.execute(
                "SELECT phone_verify_code FROM users WHERE id=?", (self.owner_id,)
            ).fetchone()
        self.assertIsNone(row[0], "no code must be stored when Twilio send fails")

    def test_payment_checkout_requires_auth_and_explicit_mode(self):
        unauthenticated = self.client.post(
            "/api/payment/liqpay/create",
            json={"plan_id": "standard"},
        )
        self.assertEqual(unauthenticated.status_code, 401)

        with mock.patch.dict(os.environ, {"LIQPAY_MODE": "disabled"}):
            disabled = self.client.post(
                "/api/payment/liqpay/create",
                json={"plan_id": "standard"},
                headers=self._auth(self.owner_token),
            )
        self.assertEqual(disabled.status_code, 503)
        self.assertEqual(disabled.get_json()["code"], "payments_disabled")

    def test_payment_checkout_uses_server_values_and_persists_owner(self):
        env = {
            "LIQPAY_MODE": "sandbox",
            "LIQPAY_PUBLIC_KEY": "sandbox_public_test",
            "LIQPAY_PRIVATE_KEY": "sandbox_private_test",
            "UA_HOMES_PUBLIC_URL": "https://ua-dim.example",
            "UA_HOMES_API": "https://api.ua-dim.example",
        }
        with mock.patch.dict(os.environ, env):
            response = self.client.post(
                "/api/payment/liqpay/create",
                json={
                    "plan_id": "standard",
                    "amount": 1,
                    "result_url": "https://attacker.example/result",
                    "server_url": "https://attacker.example/callback",
                },
                headers=self._auth(self.owner_token),
            )

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        payload = json.loads(base64.b64decode(result["data"]).decode("utf-8"))
        self.assertEqual(payload["amount"], app_module.SUBSCRIPTION_PLANS["standard"]["price"])
        self.assertEqual(payload["currency"], "UAH")
        self.assertEqual(payload["sandbox"], 1)
        self.assertEqual(
            payload["result_url"],
            f"https://ua-dim.example/real-estate-demo.html?payment=return&order_id={result['order_id']}",
        )
        self.assertEqual(
            payload["server_url"],
            "https://api.ua-dim.example/api/payment/liqpay/callback",
        )
        self.assertNotIn("attacker.example", payload["result_url"])
        self.assertNotIn("attacker.example", payload["server_url"])

        with sqlite3.connect(TEST_DB) as db:
            db.row_factory = sqlite3.Row
            order = db.execute(
                "SELECT user_id, plan_id, amount, currency, status, environment"
                " FROM premium_orders WHERE order_id = ?",
                (result["order_id"],),
            ).fetchone()
        self.assertEqual(order["user_id"], self.owner_id)
        self.assertEqual(order["plan_id"], "standard")
        self.assertEqual(order["status"], "pending")
        self.assertEqual(order["environment"], "sandbox")

    def test_payment_live_mode_rejects_sandbox_keys(self):
        with mock.patch.dict(os.environ, {
            "LIQPAY_MODE": "live",
            "LIQPAY_PUBLIC_KEY": "sandbox_public_test",
            "LIQPAY_PRIVATE_KEY": "sandbox_private_test",
        }):
            response = self.client.post(
                "/api/payment/liqpay/create",
                json={"plan_id": "standard"},
                headers=self._auth(self.owner_token),
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["code"], "payments_misconfigured")

    def test_payment_live_mode_requires_external_https_urls(self):
        for public_url in (
            "http://localhost:5050",
            "https://10.0.0.1",
            "https://127.0.0.2",
            "https://[::1]",
        ):
            with self.subTest(public_url=public_url), mock.patch.dict(os.environ, {
                "LIQPAY_MODE": "live",
                "LIQPAY_PUBLIC_KEY": "live_public_test",
                "LIQPAY_PRIVATE_KEY": "live_private_test",
                "UA_HOMES_PUBLIC_URL": public_url,
                "UA_HOMES_API": "",
            }):
                response = self.client.post(
                    "/api/payment/liqpay/create",
                    json={"plan_id": "standard"},
                    headers=self._auth(self.owner_token),
                )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json()["code"], "payments_misconfigured")

    def test_payment_migration_preserves_legacy_sandbox_environment(self):
        with sqlite3.connect(TEST_DB) as db:
            db.execute(
                "INSERT INTO premium_orders"
                " (order_id, plan_id, amount, currency, status, user_id, environment)"
                " VALUES (?, 'standard', 299, 'UAH', 'pending', ?, 'disabled')",
                ("uadim-standard-1700000000-a1b2c3d4", self.owner_id),
            )
            db.execute(
                "INSERT INTO premium_orders"
                " (order_id, plan_id, amount, currency, status, user_id, environment)"
                " VALUES (?, 'standard', 299, 'UAH', 'sandbox', ?, 'disabled')",
                ("uadim-standard-1700000001-b1c2d3e4", self.owner_id),
            )
            db.commit()
        with mock.patch.dict(os.environ, {
            "LIQPAY_PUBLIC_KEY": "sandbox_public_test",
            "LIQPAY_PRIVATE_KEY": "sandbox_private_test",
        }):
            app_module.init_db()
        with sqlite3.connect(TEST_DB) as db:
            pending_environment = db.execute(
                "SELECT environment FROM premium_orders WHERE order_id = ?",
                ("uadim-standard-1700000000-a1b2c3d4",),
            ).fetchone()[0]
            legacy_paid = db.execute(
                "SELECT environment, status, provider_status, previous_plan_id"
                " FROM premium_orders WHERE order_id = ?",
                ("uadim-standard-1700000001-b1c2d3e4",),
            ).fetchone()
        self.assertEqual(pending_environment, "sandbox")
        self.assertEqual(legacy_paid, ("sandbox", "paid", "sandbox", "free"))

    def test_payment_callback_validates_amount_and_environment(self):
        sandbox_env = {
            "LIQPAY_MODE": "sandbox",
            "LIQPAY_PUBLIC_KEY": "sandbox_public_test",
            "LIQPAY_PRIVATE_KEY": "sandbox_private_test",
        }
        with mock.patch.dict(os.environ, sandbox_env):
            created = self.client.post(
                "/api/payment/liqpay/create",
                json={"plan_id": "standard"},
                headers=self._auth(self.owner_token),
            ).get_json()
            callback = {
                "public_key": sandbox_env["LIQPAY_PUBLIC_KEY"],
                "version": "3",
                "action": "pay",
                "amount": 1,
                "currency": "UAH",
                "order_id": created["order_id"],
                "status": "sandbox",
                "payment_id": "sandbox-payment-1",
            }
            data, signature = app_module._liqpay_encode(
                callback,
                sandbox_env["LIQPAY_PRIVATE_KEY"],
            )
            invalid_signature = self.client.post(
                "/api/payment/liqpay/callback",
                data={"data": data, "signature": "invalid"},
            )
            response = self.client.post(
                "/api/payment/liqpay/callback",
                data={"data": data, "signature": signature},
            )
        self.assertEqual(invalid_signature.status_code, 400)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_data(as_text=True), "amount_mismatch")

        with sqlite3.connect(TEST_DB) as db:
            row = db.execute(
                "SELECT status FROM premium_orders WHERE order_id = ?",
                (created["order_id"],),
            ).fetchone()
            user = db.execute(
                "SELECT plan_id FROM users WHERE id = ?",
                (self.owner_id,),
            ).fetchone()
        self.assertEqual(row[0], "pending")
        self.assertEqual(user[0], "free")

    def test_payment_callback_is_idempotent_and_status_is_owner_only(self):
        env = {
            "LIQPAY_MODE": "sandbox",
            "LIQPAY_PUBLIC_KEY": "sandbox_public_test",
            "LIQPAY_PRIVATE_KEY": "sandbox_private_test",
        }
        with mock.patch.dict(os.environ, env):
            created_response = self.client.post(
                "/api/payment/liqpay/create",
                json={"plan_id": "standard"},
                headers=self._auth(self.owner_token),
            )
            created = created_response.get_json()
            checkout = json.loads(base64.b64decode(created["data"]).decode("utf-8"))
            callback = {
                "public_key": env["LIQPAY_PUBLIC_KEY"],
                "version": "3",
                "action": "pay",
                "amount": checkout["amount"],
                "currency": checkout["currency"],
                "order_id": created["order_id"],
                "status": "sandbox",
                "payment_id": "sandbox-payment-2",
            }
            data, signature = app_module._liqpay_encode(
                callback,
                env["LIQPAY_PRIVATE_KEY"],
            )
            first = self.client.post(
                "/api/payment/liqpay/callback",
                data={"data": data, "signature": signature},
            )
            with sqlite3.connect(TEST_DB) as db:
                first_expiry = db.execute(
                    "SELECT plan_expires_at FROM users WHERE id = ?",
                    (self.owner_id,),
                ).fetchone()[0]
            second = self.client.post(
                "/api/payment/liqpay/callback",
                data={"data": data, "signature": signature},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        with sqlite3.connect(TEST_DB) as db:
            order = db.execute(
                "SELECT status, provider_status, provider_payment_id"
                " FROM premium_orders WHERE order_id = ?",
                (created["order_id"],),
            ).fetchone()
            user = db.execute(
                "SELECT plan_id, plan_expires_at FROM users WHERE id = ?",
                (self.owner_id,),
            ).fetchone()
        self.assertEqual(order, ("paid", "sandbox", "sandbox-payment-2"))
        self.assertEqual(user[0], "standard")
        self.assertEqual(user[1], first_expiry)

        owner_status = self.client.get(
            f"/api/payment/orders/{created['order_id']}",
            headers=self._auth(self.owner_token),
        )
        self.assertEqual(owner_status.status_code, 200)
        self.assertTrue(owner_status.get_json()["paid"])
        realtor_status = self.client.get(
            f"/api/payment/orders/{created['order_id']}",
            headers=self._auth(self.realtor_token),
        )
        self.assertEqual(realtor_status.status_code, 404)

        failed_callback = dict(callback, status="failure")
        failed_data, failed_signature = app_module._liqpay_encode(
            failed_callback,
            env["LIQPAY_PRIVATE_KEY"],
        )
        with mock.patch.dict(os.environ, env):
            failed = self.client.post(
                "/api/payment/liqpay/callback",
                data={"data": failed_data, "signature": failed_signature},
            )
        self.assertEqual(failed.status_code, 200)
        with sqlite3.connect(TEST_DB) as db:
            still_paid = db.execute(
                "SELECT status FROM premium_orders WHERE order_id = ?",
                (created["order_id"],),
            ).fetchone()[0]
        self.assertEqual(still_paid, "paid")

        reversed_callback = dict(callback, status="reversed")
        reversed_data, reversed_signature = app_module._liqpay_encode(
            reversed_callback,
            env["LIQPAY_PRIVATE_KEY"],
        )
        with mock.patch.dict(os.environ, env):
            reversed_response = self.client.post(
                "/api/payment/liqpay/callback",
                data={"data": reversed_data, "signature": reversed_signature},
            )
        self.assertEqual(reversed_response.status_code, 200)
        with sqlite3.connect(TEST_DB) as db:
            reversed_order = db.execute(
                "SELECT status FROM premium_orders WHERE order_id = ?",
                (created["order_id"],),
            ).fetchone()[0]
            restored_user = db.execute(
                "SELECT plan_id, plan_expires_at FROM users WHERE id = ?",
                (self.owner_id,),
            ).fetchone()
        self.assertEqual(reversed_order, "reversed")
        self.assertEqual(restored_user, ("free", None))

    def test_payment_live_callback_never_accepts_sandbox_status(self):
        live_env = {
            "LIQPAY_MODE": "live",
            "LIQPAY_PUBLIC_KEY": "live_public_test",
            "LIQPAY_PRIVATE_KEY": "live_private_test",
            "UA_HOMES_PUBLIC_URL": "https://ua-dim.com",
            "UA_HOMES_API": "https://backend-production-51964.up.railway.app",
        }
        with mock.patch.dict(os.environ, live_env):
            created = self.client.post(
                "/api/payment/liqpay/create",
                json={"plan_id": "standard"},
                headers=self._auth(self.owner_token),
            ).get_json()
            checkout = json.loads(base64.b64decode(created["data"]).decode("utf-8"))
            callback = {
                "public_key": live_env["LIQPAY_PUBLIC_KEY"],
                "version": "3",
                "action": "pay",
                "amount": checkout["amount"],
                "currency": checkout["currency"],
                "order_id": created["order_id"],
                "status": "sandbox",
                "payment_id": "unexpected-sandbox-payment",
            }
            data, signature = app_module._liqpay_encode(
                callback,
                live_env["LIQPAY_PRIVATE_KEY"],
            )
            response = self.client.post(
                "/api/payment/liqpay/callback",
                data={"data": data, "signature": signature},
            )
        self.assertEqual(response.status_code, 200)
        with sqlite3.connect(TEST_DB) as db:
            order_status = db.execute(
                "SELECT status FROM premium_orders WHERE order_id = ?",
                (created["order_id"],),
            ).fetchone()[0]
            user_plan = db.execute(
                "SELECT plan_id FROM users WHERE id = ?",
                (self.owner_id,),
            ).fetchone()[0]
        self.assertEqual(order_status, "rejected")
        self.assertEqual(user_plan, "free")

    def test_payment_reversals_do_not_restore_already_refunded_plan(self):
        env = {
            "LIQPAY_MODE": "sandbox",
            "LIQPAY_PUBLIC_KEY": "sandbox_public_test",
            "LIQPAY_PRIVATE_KEY": "sandbox_private_test",
        }

        def create_and_pay(plan_id, payment_id):
            created = self.client.post(
                "/api/payment/liqpay/create",
                json={"plan_id": plan_id},
                headers=self._auth(self.owner_token),
            ).get_json()
            checkout = json.loads(base64.b64decode(created["data"]).decode("utf-8"))
            callback = {
                "public_key": env["LIQPAY_PUBLIC_KEY"],
                "version": "3",
                "action": "pay",
                "amount": checkout["amount"],
                "currency": checkout["currency"],
                "order_id": created["order_id"],
                "status": "sandbox",
                "payment_id": payment_id,
            }
            data, signature = app_module._liqpay_encode(callback, env["LIQPAY_PRIVATE_KEY"])
            response = self.client.post(
                "/api/payment/liqpay/callback",
                data={"data": data, "signature": signature},
            )
            self.assertEqual(response.status_code, 200)
            return created["order_id"], callback

        def reverse(callback):
            reversed_callback = dict(callback, status="reversed")
            data, signature = app_module._liqpay_encode(
                reversed_callback,
                env["LIQPAY_PRIVATE_KEY"],
            )
            response = self.client.post(
                "/api/payment/liqpay/callback",
                data={"data": data, "signature": signature},
            )
            self.assertEqual(response.status_code, 200)

        with mock.patch.dict(os.environ, env):
            standard_order, standard_callback = create_and_pay("standard", "payment-standard")
            premium_order, premium_callback = create_and_pay("premium", "payment-premium")
            reverse(standard_callback)
            reverse(premium_callback)

        with sqlite3.connect(TEST_DB) as db:
            statuses = dict(db.execute(
                "SELECT order_id, status FROM premium_orders"
                " WHERE order_id IN (?, ?)",
                (standard_order, premium_order),
            ).fetchall())
            user = db.execute(
                "SELECT plan_id, plan_expires_at FROM users WHERE id = ?",
                (self.owner_id,),
            ).fetchone()
        self.assertEqual(statuses[standard_order], "reversed")
        self.assertEqual(statuses[premium_order], "reversed")
        self.assertEqual(user, ("free", None))

        with mock.patch.dict(os.environ, env):
            old_standard_order, old_standard_callback = create_and_pay(
                "standard",
                "payment-old-standard",
            )
            create_and_pay("premium", "payment-middle-premium")
            create_and_pay("standard", "payment-new-standard")
            with sqlite3.connect(TEST_DB) as db:
                new_standard_expiry = db.execute(
                    "SELECT plan_expires_at FROM users WHERE id = ?",
                    (self.owner_id,),
                ).fetchone()[0]
            reverse(old_standard_callback)

        with sqlite3.connect(TEST_DB) as db:
            old_standard_status = db.execute(
                "SELECT status FROM premium_orders WHERE order_id = ?",
                (old_standard_order,),
            ).fetchone()[0]
            current_user = db.execute(
                "SELECT plan_id, plan_expires_at FROM users WHERE id = ?",
                (self.owner_id,),
            ).fetchone()
        self.assertEqual(old_standard_status, "reversed")
        self.assertEqual(current_user, ("standard", new_standard_expiry))

    def test_premium_frontend_requires_server_confirmed_status(self):
        web_dir = os.path.join(os.path.dirname(BACKEND_DIR), "web")
        with open(os.path.join(web_dir, "premium.js"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("/payment/orders/", source)
        self.assertIn("uaDim.authToken", source)
        self.assertNotIn("payment=success", source)
        self.assertNotIn("resp.demo", source)
        with open(os.path.join(web_dir, "real-estate-demo.html"), encoding="utf-8") as handle:
            shell = handle.read()
        self.assertIn("paymentParams.get('payment') === 'return'", shell)

    def test_sitemap_includes_legal_pages(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        sitemap = response.get_data(as_text=True)
        self.assertIn("/privacy.html</loc>", sitemap)
        self.assertIn("/terms.html</loc>", sitemap)
        self.assertIn("/cookie-policy.html</loc>", sitemap)

    def test_public_shell_gates_analytics_behind_consent(self):
        web_dir = os.path.join(os.path.dirname(BACKEND_DIR), "web")
        with open(os.path.join(web_dir, "real-estate-demo.html"), encoding="utf-8") as handle:
            app_shell = handle.read()
        with open(os.path.join(web_dir, "launch.html"), encoding="utf-8") as handle:
            launch_shell = handle.read()
        with open(os.path.join(web_dir, "analytics-loader.js"), encoding="utf-8") as handle:
            analytics_loader = handle.read()

        self.assertIn("privacy-consent.js", app_shell)
        self.assertIn("analytics-loader.js", app_shell)
        self.assertIn("privacy-consent.js", launch_shell)
        self.assertIn("analytics-loader.js", launch_shell)
        self.assertNotIn("googletagmanager.com/ns.html", app_shell)
        self.assertNotIn("googletagmanager.com/ns.html", launch_shell)
        self.assertIn("!analyticsAllowed()", analytics_loader)


if __name__ == "__main__":
    unittest.main()
